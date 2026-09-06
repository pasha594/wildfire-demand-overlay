"""Pull daily unique users per state (and per metro) from the PostHog API.

Queries HogQL for $pageview events on (state|fire)/... paths.

State totals are TRUE daily uniques: count(DISTINCT person_id) grouped by
(day, state extracted in SQL) — a person visiting several of a state's pages
in one day counts once. The per-page breakdown is a separate query grouped by
(day, path), where a person counts once per page they visited — so the page
list can sum to more than the state total.

Metro series are true daily uniques for the state's pages among visitors whose
GeoIP location is within RADIUS_MI of the metro's biggest city.

Requires env: POSTHOG_PERSONAL_API_KEY, POSTHOG_PROJECT_ID
(optional POSTHOG_HOST, default https://us.posthog.com). The key is only sent
to the PostHog API host and never written to any output file.
"""
import collections, datetime, json, os, re, sys, time, urllib.request

from metros import METROS, RADIUS_MI, STATE_ABBR

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "site_traffic.json")
WINDOW_START = "2026-02-26"

KEY = os.environ.get("POSTHOG_PERSONAL_API_KEY")
PROJECT = os.environ.get("POSTHOG_PROJECT_ID")
HOST = os.environ.get("POSTHOG_HOST", "https://us.posthog.com")
if not KEY or not PROJECT:
    sys.exit("POSTHOG_PERSONAL_API_KEY / POSTHOG_PROJECT_ID not set")

def hogql_page(query, attempt=0):
    req = urllib.request.Request(
        f"{HOST}/api/projects/{PROJECT}/query/",
        data=json.dumps({"query": {"kind": "HogQLQuery", "query": query}}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)["results"]
    except Exception as e:
        # PostHog intermittently 504s on heavy queries; ride it out patiently
        if attempt >= 6:
            raise
        wait = [10, 20, 30, 60, 90, 120][attempt]
        print(f"  retry in {wait}s after {type(e).__name__}", flush=True)
        time.sleep(wait)
        return hogql_page(query, attempt + 1)

PAGE = 20000

def hogql(query_with_twin, chunk_days=60):
    """Chunked fetch: personal API keys forbid OFFSET, and unstated LIMITs are
    capped, so the window is queried in date chunks (chunks split on day
    boundaries, so per-day GROUP BY distinct counts are unaffected). The query
    must contain __TWIN__ where the timestamp range filter belongs."""
    rows = []
    d0 = datetime.date.fromisoformat(WINDOW_START)
    end = datetime.date.today()
    while d0 <= end:
        d1 = min(d0 + datetime.timedelta(days=chunk_days - 1), end)
        tf = (f"timestamp >= toDateTime('{d0} 00:00:00') AND "
              f"timestamp < toDateTime('{d1 + datetime.timedelta(days=1)} 00:00:00')")
        page = hogql_page(query_with_twin.replace("__TWIN__", tf) + f" LIMIT {PAGE}")
        if len(page) >= PAGE:
            raise SystemExit(f"chunk {d0}..{d1} hit the {PAGE}-row cap — shrink chunk_days")
        rows.extend(page)
        d0 = d1 + datetime.timedelta(days=1)
    return rows

today = datetime.date.today().isoformat()
dates = []
d = datetime.date.fromisoformat(WINDOW_START)
while d.isoformat() <= today:
    dates.append(d.isoformat())
    d += datetime.timedelta(days=1)
didx = {dt: i for i, dt in enumerate(dates)}

PATH_EXPR = "extract(properties.$current_url, '((?:state|fire)/[^?#]+)')"
# state key straight in SQL: state/<key>[/...] or fire/<key>_<slug>[/...].
# Restricted to the dashboard's known state keys — the site also carries fire
# pages whose first slug segment is not a state (rx burns, non-US incidents).
STATE_EXPR = (f"extract({PATH_EXPR}, '^(?:state/|fire/)([a-z]+(?:-[a-z]+)*?)(?:[_/]|$)')")
STATE_SET = "(" + ", ".join(f"'{s}'" for s in STATE_ABBR) + ")"
BASE_WHERE = f"event = '$pageview' AND __TWIN__ AND {PATH_EXPR} != ''"

def classify(path):
    """path -> (state_key, page_kind) or (None, None). Sub-paths fold into the
    parent page; trailing-slash duplicates merge; unknown state keys drop."""
    path = path.rstrip("/")
    state, kind = None, None
    m = re.match(r"^state/([a-z-]+)(?:/.*)?$", path)
    if m:
        state, kind = m.group(1), "state_page"
    else:
        m = re.match(r"^fire/([a-z-]+?)(?:_([^/]+))?(?:/.*)?$", path)
        if m:
            state, kind = m.group(1), "fire:" + (m.group(2) or "(no-slug)")
    if state not in STATE_ABBR:
        return None, None
    return state, kind

# ---- state totals: true daily uniques per state ----
print("querying state-level daily uniques...", flush=True)
rows = hogql(f"SELECT toDate(timestamp) AS day, {STATE_EXPR} AS st, "
             f"count(DISTINCT person_id) AS users FROM events WHERE {BASE_WHERE} "
             f"AND {STATE_EXPR} IN {STATE_SET} GROUP BY day, st ORDER BY day, st")
state_total = collections.defaultdict(lambda: [0.0] * len(dates))
for day, st, users in rows:
    day = str(day)[:10]
    if day in didx:
        state_total[st][didx[day]] += users
print(f"  {len(rows)} rows -> {len(state_total)} states", flush=True)

# ---- per-page breakdown (a person counts once per page they visited) ----
print("querying per-page breakdown...", flush=True)
rows = hogql(f"SELECT toDate(timestamp) AS day, {PATH_EXPR} AS path, "
             f"count(DISTINCT person_id) AS users FROM events WHERE {BASE_WHERE} "
             f"GROUP BY day, path ORDER BY day, path", chunk_days=7)
state_pages = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0] * len(dates)))
for day, path, users in rows:
    day = str(day)[:10]
    if day not in didx:
        continue
    state, kind = classify(path)
    if state is not None:
        state_pages[state][kind][didx[day]] += users
print(f"  {len(rows)} rows", flush=True)

# ---- per-metro: true daily uniques for the state's pages near the metro ----
metro_traffic = collections.defaultdict(dict)
radius_m = int(RADIUS_MI * 1609.34)
for state, metros in METROS.items():
    for m in metros:
        rows = hogql(
            f"SELECT toDate(timestamp) AS day, count(DISTINCT person_id) AS users "
            f"FROM events WHERE {BASE_WHERE} AND {STATE_EXPR} = '{state}' "
            f"AND greatCircleDistance(toFloat(properties.$geoip_longitude), "
            f"toFloat(properties.$geoip_latitude), {m['lon']}, {m['lat']}) < {radius_m} "
            f"GROUP BY day ORDER BY day", chunk_days=190)
        series = [0.0] * len(dates)
        for day, users in rows:
            day = str(day)[:10]
            if day in didx:
                series[didx[day]] += users
        metro_traffic[state][m["key"]] = {"name": m["name"], "city": m["city"],
                                          "total": [round(v) for v in series]}
        print(f"  {state}/{m['key']}: {int(sum(series))} users within {RADIUS_MI}mi of {m['city']}", flush=True)

out = {
    "dates": dates,
    "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
    "source": "posthog-api",
    "states": {
        s: {
            "total": [round(v, 1) for v in series],
            "pages": {k: v for k, v in state_pages[s].items()},
            "metros": metro_traffic.get(s, {}),
        }
        for s, series in state_total.items()
    },
}
with open(OUT, "w") as f:
    json.dump(out, f)
print(f"wrote {OUT}: {len(dates)} days ({dates[0]}..{dates[-1]}), {len(state_total)} states")
