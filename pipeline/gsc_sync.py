"""Sync Google Search Console Search Analytics into a local SQLite DB, then
export dashboard aggregates to gsc_daily.json.

Usage:
    gsc_sync.py               refetch recent days (default; see below) + export
    gsc_sync.py --backfill    refetch the full retention window (~16 months) + export
    gsc_sync.py --start YYYY-MM-DD [--end YYYY-MM-DD]   explicit range + export
    gsc_sync.py --export-only rebuild gsc_daily.json from the DB, no API calls

Default window: the last 7 days, extended back to 3 days before the end of the
last successful sync if that is older, so gaps from missed runs refill
themselves. Each fetched (search type, day) is replaced wholesale — rows are
deleted and re-inserted in one transaction — so Google's revisions, including
rows that disappear, are picked up exactly.

Auth: Application Default Credentials from `gcloud auth application-default
login` (webmasters.readonly). The quota project is set here in code, so the
script does not depend on the ADC file's quota_project_id. No credentials are
stored by this script.

Two request shapes per day, because Google drops privacy-filtered queries
whenever the query dimension is requested:
    page_daily   dims date+page        -> complete totals (used for state series)
    query_daily  dims date+query+page  -> query detail (city slices, top queries)
Discover and Google News cannot be grouped by query, so they only get page_daily.

Exit codes: 0 ok, 1 API/data failure, 2 credentials need re-login.
"""
import argparse, collections, concurrent.futures, datetime, json, logging, os, re, sqlite3, sys, time, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "gsc.sqlite")
EXPORT_PATH = os.path.join(BASE, "gsc_daily.json")

PROPERTY = "https://fires.cornea.is/"   # URL-prefix property: continuous history (the sc-domain:cornea.is
                                        # domain property has multi-month gaps)
SITE_HOST = "fires.cornea.is"
QUOTA_PROJECT = "gen-lang-client-0984582838"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
SEARCH_TYPES = ["web", "image", "video", "news", "discover", "googleNews"]
NO_QUERY_TYPES = {"discover", "googleNews"}
RETENTION_DAYS = 486                     # Search Console keeps ~16 months
DEFAULT_DAYS = 7
PAGE_SIZE = 25000
EXPORT_START = "2026-02-26"              # dashboard window start
TOP_N = 20

log = logging.getLogger("gsc_sync")


# ---------------------------------------------------------------- API
def session():
    import google.auth
    from google.auth.exceptions import RefreshError, DefaultCredentialsError
    from google.auth.transport.requests import AuthorizedSession
    try:
        creds, _ = google.auth.default(scopes=SCOPES, quota_project_id=QUOTA_PROJECT)
        s = AuthorizedSession(creds)
        r = s.get("https://searchconsole.googleapis.com/webmasters/v3/sites", timeout=60)
    except (RefreshError, DefaultCredentialsError) as e:
        log.error("credentials unusable (%s). Re-run: gcloud auth application-default login "
                  "--scopes=https://www.googleapis.com/auth/webmasters.readonly,"
                  "https://www.googleapis.com/auth/cloud-platform", e)
        sys.exit(2)
    if r.status_code != 200:
        log.error("sites.list failed: HTTP %s %s", r.status_code, r.text[:300])
        sys.exit(1)
    sites = [e["siteUrl"] for e in r.json().get("siteEntry", [])]
    if PROPERTY not in sites:
        log.error("property %s not visible to these credentials (have: %s)", PROPERTY, sites)
        sys.exit(1)
    return s


QUERY_URL = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
             + urllib.parse.quote(PROPERTY, safe="") + "/searchAnalytics/query")


def fetch(s, day, stype, dims):
    """All rows for one day / search type / dimension set, paging by startRow."""
    rows, start, meta = [], 0, None
    while True:
        body = {"startDate": day, "endDate": day, "dimensions": dims, "type": stype,
                "dataState": "all", "rowLimit": PAGE_SIZE, "startRow": start}
        for attempt in range(6):
            try:
                r = s.post(QUERY_URL, json=body, timeout=120)
            except Exception as e:  # network hiccup
                r, err = None, e
            if r is not None and r.status_code == 200:
                break
            # Search Analytics signals QPS/load quota as HTTP 403 ("quota exceeded"), not only 429
            quota = r is not None and r.status_code == 403 and "quota" in r.text.lower()
            if r is not None and not quota and r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"{stype} {day} {dims}: HTTP {r.status_code} {r.text[:300]}")
            wait = ([20, 40, 60, 120, 180, 240] if quota else [5, 15, 30, 60, 120, 180])[attempt]
            log.warning("%s %s %s: %s, retrying in %ss", stype, day, "/".join(dims),
                        f"HTTP {r.status_code}" if r is not None else type(err).__name__, wait)
            time.sleep(wait)
        else:
            raise RuntimeError(f"{stype} {day} {dims}: retries exhausted")
        d = r.json()
        page = d.get("rows", [])
        rows.extend(page)
        m = d.get("metadata") or {}
        meta = meta or m.get("firstIncompleteDate") or m.get("first_incomplete_date")
        if len(page) < PAGE_SIZE:
            return rows, meta
        start += PAGE_SIZE


# ---------------------------------------------------------------- DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS page_daily (
    search_type TEXT, date TEXT, page TEXT,
    clicks INTEGER, impressions INTEGER, ctr REAL, position REAL,
    PRIMARY KEY (search_type, date, page));
CREATE TABLE IF NOT EXISTS query_daily (
    search_type TEXT, date TEXT, query TEXT, page TEXT,
    clicks INTEGER, impressions INTEGER, ctr REAL, position REAL,
    PRIMARY KEY (search_type, date, query, page));
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
    mode TEXT, start_date TEXT, end_date TEXT, status TEXT, first_incomplete_date TEXT,
    page_rows INTEGER, query_rows INTEGER, message TEXT);
CREATE INDEX IF NOT EXISTS qd_date ON query_daily (date);
"""


def db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    return con


def page_path(url):
    """https://fires.cornea.is/fire/x -> fire/x (compact storage)."""
    p = urllib.parse.urlsplit(url)
    return (p.netloc + p.path) if p.netloc != SITE_HOST else p.path.lstrip("/")


def merge(rows, keyfn):
    """Combine rows that normalize to the same key (http/https or www variants of one
    page in a domain property): sum clicks/impressions, impression-weight position,
    recompute CTR. -> {key: (clicks, impressions, ctr, position)}"""
    acc = {}
    for r in rows:
        k = keyfn(r)
        c, i, pw, n = acc.get(k, (0, 0, 0.0, 0))
        pos = r.get("position") or 0
        acc[k] = (c + int(r["clicks"]), i + int(r["impressions"]), pw + pos * int(r["impressions"]), n + 1)
    return {k: (c, i, (c / i) if i else None, (pw / i) if i else None) for k, (c, i, pw, n) in acc.items()}


def sync_day(s, con, day):
    jobs = [(t, ("date", "page")) for t in SEARCH_TYPES] + \
           [(t, ("date", "query", "page")) for t in SEARCH_TYPES if t not in NO_QUERY_TYPES]
    # 3 concurrent requests stays under Search Analytics' per-second quota (10 tripped it)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(fetch, s, day, t, list(dims)): (t, dims) for t, dims in jobs}
        results = {futs[f]: f.result() for f in concurrent.futures.as_completed(futs)}
    n_page = n_query = 0
    first_incomplete = None
    with con:  # one transaction per day: delete then re-insert everything fetched
        for (t, dims), (rows, meta) in results.items():
            first_incomplete = min(filter(None, [first_incomplete, meta]), default=None)
            if dims == ("date", "page"):
                con.execute("DELETE FROM page_daily WHERE search_type=? AND date=?", (t, day))
                con.executemany("INSERT INTO page_daily VALUES (?,?,?,?,?,?,?)",
                                [(t, day, *k, *v) for k, v in merge(rows, lambda r: (page_path(r["keys"][1]),)).items()])
                n_page += len(rows)
            else:
                con.execute("DELETE FROM query_daily WHERE search_type=? AND date=?", (t, day))
                con.executemany("INSERT INTO query_daily VALUES (?,?,?,?,?,?,?,?)",
                                [(t, day, *k, *v) for k, v in merge(rows, lambda r: (r["keys"][1], page_path(r["keys"][2]))).items()])
                n_query += len(rows)
    return n_page, n_query, first_incomplete


# ---------------------------------------------------------------- export
def load_json(name):
    with open(os.path.join(BASE, name)) as f:
        return json.load(f)


def classify(path, known):
    """page path -> dashboard state key, mirroring fetch_traffic.classify()."""
    path = path.rstrip("/")
    m = re.match(r"^state/([a-z-]+)(?:/.*)?$", path) or re.match(r"^fire/([a-z-]+?)(?:_[^/]+)?(?:/.*)?$", path)
    s = m.group(1) if m else None
    return s if s in known else None


def export(con):
    from metros import METROS, STATE_ABBR
    known = set(STATE_ABBR)
    last = con.execute("SELECT MAX(date) FROM page_daily WHERE search_type='web'").fetchone()[0]
    if not last:
        raise RuntimeError("no Search Console rows in the DB yet — run a sync first")
    run = con.execute("SELECT first_incomplete_date FROM runs WHERE status='ok' "
                      "ORDER BY id DESC LIMIT 1").fetchone()
    fid = run[0] if run and run[0] else None
    last_complete = (datetime.date.fromisoformat(fid) - datetime.timedelta(days=1)).isoformat() if fid else last
    last_complete = min(last_complete, last)

    dates = []
    d = datetime.date.fromisoformat(EXPORT_START)
    while d.isoformat() <= last:
        dates.append(d.isoformat())
        d += datetime.timedelta(days=1)
    di = {x: i for i, x in enumerate(dates)}
    N = len(dates)

    def blank():
        return {"c": [0] * N, "i": [0] * N, "pw": [0.0] * N}

    state_cache = {}
    def st_of(p):
        if p not in state_cache:
            state_cache[p] = classify(p, known)
        return state_cache[p]

    # state totals per type (complete, from page_daily)
    states = collections.defaultdict(lambda: collections.defaultdict(blank))
    site = collections.defaultdict(blank)
    for t, day, page, c, i, pos in con.execute(
            "SELECT search_type, date, page, clicks, impressions, position FROM page_daily WHERE date >= ?",
            (EXPORT_START,)):
        k = di.get(day)
        if k is None:
            continue
        for bucket in filter(None, [site[t], states[st_of(page)][t] if st_of(page) else None]):
            bucket["c"][k] += c
            bucket["i"][k] += i
            bucket["pw"][k] += (pos or 0) * i

    # metro slices: queries mentioning the metro's biggest city, landing on that state's pages
    city_rx = {s: [(m["key"], re.compile(r"\b" + re.escape(m["city"]) + r"\b")) for m in ms]
               for s, ms in METROS.items()}
    metros = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(blank)))
    for t, day, q, page, c, i, pos in con.execute(
            "SELECT search_type, date, query, page, clicks, impressions, position FROM query_daily WHERE date >= ?",
            (EXPORT_START,)):
        s = st_of(page)
        if not s or s not in city_rx:
            continue
        k = di.get(day)
        for mkey, rx in city_rx[s]:
            if rx.search(q):
                b = metros[s][mkey][t]
                b["c"][k] += c
                b["i"][k] += i
                b["pw"][k] += (pos or 0) * i

    # days actually fetched by a successful run; anything else is "no data", not zero
    covered = set()
    for a, b in con.execute("SELECT start_date, end_date FROM runs WHERE status='ok'"):
        d = datetime.date.fromisoformat(a)
        while d.isoformat() <= b:
            covered.add(d.isoformat())
            d += datetime.timedelta(days=1)
    cov = [dates[k] in covered for k in range(N)]

    def finish(b):
        """-> compact {c, i, p}; p = impression-weighted avg position. None = day not fetched
        (c/i/p) or no impressions that day (p only)."""
        if not any(b["i"]) and not any(b["c"]):
            return None
        return {"c": [b["c"][k] if cov[k] else None for k in range(N)],
                "i": [b["i"][k] if cov[k] else None for k in range(N)],
                "p": [round(b["pw"][k] / b["i"][k], 1) if cov[k] and b["i"][k] else None for k in range(N)]}

    out_states = {}
    for s in sorted(states):
        types = {t: v for t in SEARCH_TYPES if (v := finish(states[s][t]))}
        ms = {}
        for mkey, per_t in metros.get(s, {}).items():
            mt = {t: v for t in SEARCH_TYPES if (v := finish(per_t[t]))}
            if mt:
                ms[mkey] = mt
        out_states[s] = {"types": types, "metros": ms}

    # top queries: last 7 complete days vs the 7 before, per query-capable type
    end = datetime.date.fromisoformat(last_complete)
    w1 = ((end - datetime.timedelta(days=6)).isoformat(), end.isoformat())
    w0 = ((end - datetime.timedelta(days=13)).isoformat(), (end - datetime.timedelta(days=7)).isoformat())
    top = {}
    for t in SEARCH_TYPES:
        if t in NO_QUERY_TYPES:
            continue
        cur = collections.defaultdict(lambda: {"c": 0, "i": 0, "pw": 0.0, "pages": collections.Counter()})
        prev = collections.Counter()
        for q, day, page, c, i, pos in con.execute(
                "SELECT query, date, page, clicks, impressions, position FROM query_daily "
                "WHERE search_type=? AND date BETWEEN ? AND ?", (t, w0[0], w1[1])):
            if day >= w1[0]:
                r = cur[q]
                r["c"] += c
                r["i"] += i
                r["pw"] += (pos or 0) * i
                r["pages"][page] += i
            else:
                prev[q] += i
        rows = []
        for q, r in cur.items():
            if not r["i"]:
                continue
            page = r["pages"].most_common(1)[0][0]
            rows.append({"q": q, "state": st_of(page), "page": page, "i": r["i"], "i0": prev.get(q, 0),
                         "c": r["c"], "ctr": round(r["c"] / r["i"], 4), "pos": round(r["pw"] / r["i"], 1)})
        if not rows:
            continue
        rising = sorted(rows, key=lambda r: r["i"] - r["i0"], reverse=True)[:TOP_N]
        rising = [r for r in rising if r["i"] > r["i0"]]
        unranked = sorted([r for r in rows if r["pos"] > 10 and r["i"] >= 20],
                          key=lambda r: r["i"], reverse=True)[:TOP_N]
        top[t] = {"rising": rising, "unranked": unranked}

    out = {
        "meta": {"property": PROPERTY, "page_filter": SITE_HOST,
                 "exported_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
                 "last_date": last, "last_complete_date": last_complete,
                 "top_window": [w1[0], w1[1]], "prev_window": [w0[0], w0[1]],
                 "types": [t for t in SEARCH_TYPES if finish(site[t])],
                 "covered_from": min((d for d in dates if d in covered), default=None),
                 "dates": dates},
        "site": {t: v for t in SEARCH_TYPES if (v := finish(site[t]))},
        "states": out_states,
        "top_queries": top,
    }
    tmp = EXPORT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    os.replace(tmp, EXPORT_PATH)
    log.info("exported %s (%d KB): %d days %s..%s (complete through %s), %d states, %d metro slices, top-query types %s",
             os.path.basename(EXPORT_PATH), os.path.getsize(EXPORT_PATH) // 1024, N, dates[0], last,
             last_complete, len(out_states), sum(len(v["metros"]) for v in out_states.values()), list(top))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--backfill", action="store_true", help="refetch the full ~16-month retention window")
    g.add_argument("--start", help="explicit start date YYYY-MM-DD")
    g.add_argument("--export-only", action="store_true", help="rebuild gsc_daily.json from the DB only")
    ap.add_argument("--end", help="explicit end date YYYY-MM-DD (default today)")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", stream=sys.stdout)
    logging.getLogger("google.auth._default").setLevel(logging.ERROR)  # "no project ID" is expected with ADC
    con = db()
    if a.export_only:
        export(con)
        return

    today = datetime.date.today()
    end = datetime.date.fromisoformat(a.end) if a.end else today
    floor = today - datetime.timedelta(days=RETENTION_DAYS)
    if a.backfill:
        mode, start = "backfill", floor
    elif a.start:
        mode, start = "range", datetime.date.fromisoformat(a.start)
    else:
        mode, start = "default", today - datetime.timedelta(days=DEFAULT_DAYS)
        prev = con.execute("SELECT MAX(end_date) FROM runs WHERE status='ok'").fetchone()[0]
        if prev:
            start = min(start, datetime.date.fromisoformat(prev) - datetime.timedelta(days=3))
    start = max(start, floor)

    run_id = con.execute("INSERT INTO runs (started_at, mode, start_date, end_date, status) VALUES (?,?,?,?,?)",
                         (datetime.datetime.now().isoformat(timespec="seconds"), mode,
                          start.isoformat(), end.isoformat(), "running")).lastrowid
    con.commit()
    log.info("sync %s: %s..%s (%d days), property %s, types %s",
             mode, start, end, (end - start).days + 1, PROPERTY, SEARCH_TYPES)
    try:
        s = session()
        tot_p = tot_q = 0
        first_incomplete = None
        day = start
        t0 = time.time()
        while day <= end:
            n_p, n_q, fi = sync_day(s, con, day.isoformat())
            tot_p += n_p
            tot_q += n_q
            first_incomplete = min(filter(None, [first_incomplete, fi]), default=None)
            done = (day - start).days + 1
            total = (end - start).days + 1
            if done % 30 == 0 or day == end or total <= 14:
                log.info("  %s done (%d/%d days, %d page rows, %d query rows, %.0fs)",
                         day, done, total, tot_p, tot_q, time.time() - t0)
            day += datetime.timedelta(days=1)
        con.execute("UPDATE runs SET finished_at=?, status='ok', first_incomplete_date=?, page_rows=?, "
                    "query_rows=? WHERE id=?", (datetime.datetime.now().isoformat(timespec="seconds"),
                                                first_incomplete, tot_p, tot_q, run_id))
        con.commit()
        log.info("sync ok: %d page rows, %d query rows; first incomplete date: %s",
                 tot_p, tot_q, first_incomplete or "none reported")
        export(con)
    except SystemExit:
        raise
    except Exception as e:
        con.execute("UPDATE runs SET finished_at=?, status='failed', message=? WHERE id=?",
                    (datetime.datetime.now().isoformat(timespec="seconds"), str(e)[:500], run_id))
        con.commit()
        log.exception("sync FAILED: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
