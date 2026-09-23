"""Build the self-contained dashboard HTML.

Inputs: site_traffic.json (per-state daily users), trends_data.json (Google
Trends, geo=US-{abbr}, in-state), trends_data_national.json (geo=US).
Output: dashboard.html with an in-state <-> national toggle.
"""
import json, math, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "dashboard.html")

# national mode and the 2025 overlay are descoped (user request 2026-09-03);
# flip these and re-add the fetch passes in refresh.py to bring them back
INCLUDE_NATIONAL = False
INCLUDE_2025 = False

with open(os.path.join(BASE, "site_traffic.json")) as f:
    traffic = json.load(f)
with open(os.path.join(BASE, "trends_data.json")) as f:
    tr_state = json.load(f)
fires_by_state = {}
fires_path = os.path.join(BASE, "fires.json")
if os.path.exists(fires_path):
    with open(fires_path) as f:
        fires_by_state = json.load(f)["states"]

def load_opt(name):
    p = os.path.join(BASE, name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None

tr_natl = load_opt("trends_data_national.json") if INCLUDE_NATIONAL else None
tr25_state = load_opt("trends_data_2025.json") if INCLUDE_2025 else None
tr25_natl = load_opt("trends_data_2025_national.json") if INCLUDE_2025 else None
tr_metro = load_opt("trends_data_metro.json")
maps = load_opt("maps.json") or {}

dates = traffic["dates"]
fetched_at = traffic.get("fetched_at")

# keep the axis inside the trends window: if traffic is fresher than trends
# (e.g. a failed trends step), truncate rather than plot phantom zero-trend days
trends_end = tr_state["meta"]["timeframe"].split()[1]
if dates and dates[-1] > trends_end:
    cut = sum(1 for d in dates if d <= trends_end)
    print(f"note: traffic runs {len(dates) - cut} day(s) past trends ({trends_end}); truncating axis")
    dates = dates[:cut]
    for _s in traffic["states"].values():
        _s["total"] = _s["total"][:cut]
        if _s.get("organic"):
            _s["organic"] = _s["organic"][:cut]
        _s["pages"] = {k: v[:cut] for k, v in _s["pages"].items()}
        for _m in (_s.get("metros") or {}).values():
            _m["total"] = _m["total"][:cut]

def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)

def mode_payload(entry, total_series):
    """Per-mode keyword series + mode-dependent stats for one state."""
    if not entry:
        return None
    kws = entry["keywords"]
    if entry["dates"] != dates:
        idx = {d: i for i, d in enumerate(entry["dates"])}
        for kw in kws:
            s = entry["series"][kw]
            entry["series"][kw] = [s[idx[d]] if d in idx and idx[d] < len(s) else 0 for d in dates]
    kw_series = [entry["series"].get(k) or [0] * len(dates) for k in kws]
    best_kw, best_val, best_day = None, -1, 0
    for k, s in zip(kws, kw_series):
        for i, v in enumerate(s):
            if v > best_val:
                best_kw, best_val, best_day = k, v, i
    mean_kw = [sum(s[i] for s in kw_series) / len(kw_series) for i in range(len(dates))]
    r = pearson(total_series, mean_kw) if total_series else None
    return {
        "kwSeries": [[round(float(v), 1) for v in s] for s in kw_series],
        "searchPeakDate": dates[best_day] if best_val > 0 else None,
        "searchPeakKw": best_kw if best_val > 0 else None,
        "r": round(r, 2) if r is not None else None,
    }

def align_25(entry25, kws):
    """2025 keyword series aligned by day index (both windows are 181 non-leap days)."""
    if not entry25:
        return None
    out = []
    for k in kws:
        s = [round(float(v), 1) for v in (entry25["series"].get(k) or [])][:len(dates)]
        s += [0] * (len(dates) - len(s))
        out.append(s)
    return out

all_keys = sorted(set(tr_state["states"]) | (set(tr_natl["states"]) if tr_natl else set()))
states_payload = []
for key in all_keys:
    e_state = tr_state["states"].get(key)
    e_natl = tr_natl["states"].get(key) if tr_natl else None
    e25_state = tr25_state["states"].get(key) if tr25_state else None
    e25_natl = tr25_natl["states"].get(key) if tr25_natl else None
    ref = e_state or e_natl
    tinfo = traffic["states"].get(key)

    total_series = tinfo["total"] if tinfo else None
    stats, pages_label, pages_title = None, None, None
    if tinfo:
        peak_i = max(range(len(total_series)), key=lambda i: total_series[i])
        stats = {
            "total": round(sum(total_series)),
            "peakTrafficDate": dates[peak_i],
            "peakTrafficVal": round(total_series[peak_i]),
        }
        page_keys = tinfo["pages"]
        n_fire = sum(1 for p in page_keys if p.startswith("fire:"))
        has_state = "state_page" in page_keys
        parts = []
        if has_state:
            parts.append("state page")
        if n_fire:
            parts.append(f"{n_fire} fire page{'s' if n_fire > 1 else ''}")
        pages_label = " + ".join(parts)
        detail = []
        if has_state:
            detail.append([f"state/{key}", round(sum(page_keys["state_page"]))])
        for p in sorted((p for p in page_keys if p.startswith('fire:')),
                        key=lambda p: -sum(page_keys[p])):
            detail.append([f"fire/{key}_{p[5:]}", round(sum(page_keys[p]))])
        pages_title = detail

    mode_state = mode_payload(e_state, total_series)
    mode_natl = mode_payload(e_natl, total_series)
    if mode_state:
        mode_state["kw25"] = align_25(e25_state, ref["keywords"])
    if mode_natl:
        mode_natl["kw25"] = align_25(e25_natl, ref["keywords"])

    metros_payload = []
    for mkey, minfo in sorted((tinfo.get("metros") or {}).items() if tinfo else []):
        m_entry = tr_metro["states"].get(f"{key}/{mkey}") if tr_metro else None
        m_traffic = minfo["total"]
        m_mode = mode_payload(m_entry, m_traffic)
        metros_payload.append({
            "key": mkey,
            "name": minfo["name"],
            "traffic": m_traffic,
            "city": minfo.get("city"),
            "kws": m_entry["keywords"] if m_entry else None,
            "mode": m_mode,
        })
    metros_payload.sort(key=lambda m: m["name"])

    states_payload.append({
        "key": key,
        "name": key.replace("_", " ").replace("-", " ").title(),
        "abbr": ref["abbr"],
        "traffic": [round(v) for v in total_series] if total_series else None,
        "organic": (tinfo.get("organic") if tinfo else None),
        "pagesLabel": pages_label,
        "pagesDetail": pages_title,
        "kws": ref["keywords"],
        "fires": [dict(
                      {"t": fi["t"], "d": fi["d"], "a": fi["a"], "p": fi.get("p"), "fr": fi.get("fr"),
                       "act": bool(fi.get("active"))},
                      **(dict(zip(("lat", "lon"),
                                  (round(float(c), 4) for c in fi["coords"].split(","))))
                         if fi.get("coords") else {}))
                  for fi in fires_by_state.get(key, [])],
        "modes": {
            "state": mode_state,
            "national": mode_natl,
        },
        "metros": metros_payload,
        "stats": stats,
    })

states_payload.sort(key=lambda s: s["name"])


def null_dropouts(modes, what):
    """Google Trends sometimes returns an all-zero day for many geos at once. A geo is
    "steady" on day k if it was non-zero on at least 5 of the 7 days before. If 30% or
    more of steady geos read all-zero on day k (normal days: 0-15%), the day is a
    dropout and those steady geos' zeros become missing (None). Geos that are often
    zero are never steady, so their genuine zeros are kept."""
    modes = [m for m in modes if m and m.get("kwSeries")]
    if not modes:
        return []
    n = len(dates)
    nz = [[any((s[k] if len(s) > k else 0) or 0 for s in m["kwSeries"]) for k in range(n)] for m in modes]
    flagged = []
    for k in range(7, n):
        steady = [g for g in range(len(modes)) if sum(nz[g][k - 7:k]) >= 5]
        if len(steady) < 10:
            continue
        dead = [g for g in steady if not nz[g][k]]
        if len(dead) >= 0.3 * len(steady):
            flagged.append((k, dead, len(steady)))
    for k, dead, _ in flagged:
        for g in dead:
            for s in modes[g]["kwSeries"]:
                if len(s) > k:
                    s[k] = None
    if flagged:
        print(f"note: {what} dropout days set to missing: "
              + ", ".join(f"{dates[k]} ({len(d)}/{ns} steady geos all-zero)" for k, d, ns in flagged))
    return [dates[k] for k, _, _ in flagged]


dropout_days = null_dropouts([mp["mode"] for sp in states_payload for mp in sp["metros"]], "metro trends")
dropout_days += null_dropouts([sp["modes"]["state"] for sp in states_payload], "state trends")

# ---- Search Console (optional; produced locally by gsc_sync.py) ----
gsc_raw = load_opt("gsc_daily.json")
gsc_payload = None
if gsc_raw:
    gidx = {d: k for k, d in enumerate(gsc_raw["meta"]["dates"])}

    last_complete = gsc_raw["meta"]["last_complete_date"]

    def galign(t):
        """{c,i,p} on the GSC date axis -> same on the dashboard axis; None where GSC has no
        day, and for the partial days after the last complete one."""
        pos = [gidx.get(d) if d <= last_complete else None for d in dates]
        return {f: [t[f][k] if k is not None else None for k in pos] for f in ("c", "i", "p")}

    in_window = lambda t: any((v or 0) > 0 for v in galign(t)["i"])
    for sp in states_payload:
        g = gsc_raw["states"].get(sp["key"])
        if not g:
            continue
        sp["gsc"] = {t: galign(v) for t, v in g["types"].items() if in_window(v)}
        for mp in sp["metros"]:
            mg = g["metros"].get(mp["key"])
            if mg:
                mp["gsc"] = {t: galign(v) for t, v in mg.items() if in_window(v)}
    gm = gsc_raw["meta"]
    gsc_payload = {
        "property": gm["property"], "pageFilter": gm["page_filter"], "exportedAt": gm["exported_at"],
        "lastDate": gm["last_date"], "lastComplete": gm["last_complete_date"], "coveredFrom": gm.get("covered_from"),
        "types": [t for t in gm["types"] if any(t in (sp.get("gsc") or {}) for sp in states_payload)],
        "topWindow": gm["top_window"], "prevWindow": gm["prev_window"],
        "topQueries": gsc_raw["top_queries"],
    }
    print(f"search console: {gm['property']} through {gm['last_date']} (complete through {gm['last_complete_date']}), "
          f"types {gsc_payload['types']}, {sum(1 for sp in states_payload if sp.get('gsc'))} states, "
          f"{sum(1 for sp in states_payload for mp in sp['metros'] if mp.get('gsc'))} metro slices")

payload = {"dates": dates, "timeframe": tr_state["meta"]["timeframe"],
           "has25": bool(tr25_state or tr25_natl), "hasNatl": bool(tr_natl),
           "fetchedAt": fetched_at, "states": states_payload, "maps": maps, "gsc": gsc_payload}
generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ")

HTML = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wildfire Demand Overlay</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root {
    color-scheme: light;
    --bg: #f9f9f7;
    --surface: #fcfcfb;
    --ink: #0b0b0b;
    --ink-2: #52514e;
    --muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11,11,11,.10);
    --wf: #eb6834;      /* wildfire */
    --f: #1baf7a;       /* fire */
    --fm: #2a78d6;      /* fire map */
    --fn: #4a3aa7;      /* fire near */
    --gi: #e87ba4;      /* search console impressions */
    --gc: #2a78d6;      /* search console clicks / CTR */
    --gp: var(--ink);   /* search console avg position (dotted) */
    --range-bg: rgba(42,120,214,.13);   /* date picker: days inside the range */
    --traffic: #6f6d67;
    --traffic-fill: rgba(137,135,129,.20);
    --fire-mk: #eda100;
    --chip-bg: rgba(11,11,11,.045);
    --tooltip-bg: #ffffff;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --bg: #0d0d0d;
      --surface: #1a1a19;
      --ink: #ffffff;
      --ink-2: #c3c2b7;
      --muted: #898781;
      --grid: #2c2c2a;
      --axis: #383835;
      --border: rgba(255,255,255,.10);
      --wf: #d95926;
      --f: #199e70;
      --fm: #3987e5;
      --fn: #9085e9;
      --gi: #d55181;
      --gc: #3987e5;
      --range-bg: rgba(57,135,229,.24);
      --traffic: #a3a19a;
      --traffic-fill: rgba(137,135,129,.22);
      --fire-mk: #c98500;
      --chip-bg: rgba(255,255,255,.06);
      --tooltip-bg: #242423;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg: #0d0d0d;
    --surface: #1a1a19;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,.10);
    --wf: #d95926;
    --f: #199e70;
    --fm: #3987e5;
    --fn: #9085e9;
    --gi: #d55181;
    --gc: #3987e5;
    --range-bg: rgba(57,135,229,.24);
    --traffic: #a3a19a;
    --traffic-fill: rgba(137,135,129,.22);
    --fire-mk: #c98500;
    --chip-bg: rgba(255,255,255,.06);
    --tooltip-bg: #242423;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.45;
  }
  .wrap { max-width: 1440px; margin: 0 auto; padding: 28px 24px 64px; }

  header.page { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 18px; margin-bottom: 6px; }
  h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.01em; margin: 0; }
  .meta { color: var(--muted); font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; }
  .sub { color: var(--ink-2); margin: 0 0 18px; max-width: 72ch; }

  .controls {
    position: sticky; top: 0; z-index: 5;
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px;
    padding: 10px 12px; margin: 0 -12px 18px;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
  }
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 999px; overflow: hidden; margin-right: 6px; }
  .seg button {
    font: inherit; font-size: 12.5px; padding: 4px 12px; cursor: pointer;
    border: 0; background: transparent; color: var(--ink-2);
  }
  .seg button.on { background: var(--ink); color: var(--bg); font-weight: 600; }
  .seg button:focus-visible { outline: 2px solid var(--fm); outline-offset: -2px; }
  .lg {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 4px 10px 4px 7px; border-radius: 999px;
    border: 1px solid var(--border); background: var(--chip-bg);
    color: var(--ink-2); font: inherit; font-size: 12.5px; cursor: pointer;
  }
  .lg:hover { border-color: var(--muted); }
  .lg:focus-visible { outline: 2px solid var(--fm); outline-offset: 1px; }
  .lg.off { opacity: .38; }
  .impact { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--ink-2);
    border: 1px solid var(--border); border-radius: 999px; padding: 3px 12px; background: var(--chip-bg); }
  .impact input[type=range] { width: 88px; accent-color: var(--fire-mk); margin: 0; }
  .impact b { font-family: "IBM Plex Mono", ui-monospace, monospace; font-weight: 500; color: var(--ink);
    min-width: 42px; text-align: center; font-variant-numeric: tabular-nums; }
  .lg.off .sw { text-decoration: line-through; }
  .lg svg { display: block; }
  .controls .gap { flex: 1; }
  .controls .cbreak { flex-basis: 100%; height: 0; }
  .dbtn { font-variant-numeric: tabular-nums; color: var(--ink); font-weight: 500; }
  .dbtn .lbl { color: var(--muted); font-weight: 400; }
  details.pop.dpick .popbody { flex-direction: row; align-items: flex-start; gap: 14px; padding: 12px; }
  .dpresets { display: flex; flex-direction: column; gap: 2px; min-width: 116px; }
  .dpresets button { font: inherit; font-size: 12.5px; text-align: left; padding: 5px 9px; border: 0; border-radius: 6px;
    background: transparent; color: var(--ink-2); cursor: pointer; white-space: nowrap; }
  .dpresets button:hover { background: var(--chip-bg); }
  .dpresets button.on { background: var(--ink); color: var(--bg); font-weight: 600; }
  .dcals { display: flex; gap: 18px; border-left: 1px solid var(--border); padding-left: 14px; }
  .dcal { width: 212px; }
  .dchead { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 10.5px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
  .dchead b { color: var(--ink); font-weight: 600; text-transform: none; letter-spacing: 0; font-family: "IBM Plex Sans", system-ui, sans-serif; font-size: 12.5px; margin-left: 4px; }
  .dcnav { display: flex; align-items: center; justify-content: space-between; font-size: 12.5px; font-weight: 600;
    color: var(--ink); margin-bottom: 4px; }
  .dnav { font: inherit; font-size: 15px; line-height: 1; width: 26px; height: 26px; border: 1px solid var(--border);
    border-radius: 6px; background: transparent; color: var(--ink-2); cursor: pointer; }
  .dnav:disabled { opacity: .3; cursor: default; }
  .dgrid { display: grid; grid-template-columns: repeat(7, 1fr); row-gap: 2px; }
  .dgrid .dow { font-size: 10.5px; color: var(--muted); text-align: center; padding: 2px 0 4px; }
  .dday { font: inherit; font-size: 12px; height: 28px; padding: 0; border: 0; border-radius: 0; background: transparent;
    color: var(--ink); cursor: pointer; font-variant-numeric: tabular-nums; }
  .dday:hover:not(:disabled) { box-shadow: inset 0 0 0 1px var(--muted); border-radius: 6px; }
  .dday:disabled { color: var(--axis); cursor: default; }
  .dday.in { background: var(--range-bg); }
  .dday.rs { border-radius: 6px 0 0 6px; }
  .dday.re { border-radius: 0 6px 6px 0; }
  .dday.rs.re, .dday.pick { border-radius: 6px; }
  .dday.pick { background: var(--ink); color: var(--bg); font-weight: 600; }
  .dday:focus-visible, .dnav:focus-visible, .dpresets button:focus-visible { outline: 2px solid var(--fm); outline-offset: -2px; }
  .card, .mapcard { scroll-margin-top: calc(var(--ctrl-h, 0px) + 10px); }
  @media (max-width: 700px) {
    .controls { position: static; }
    details.pop.dpick .popbody { flex-direction: column; max-width: calc(100vw - 24px); }
    .dpresets { flex-direction: row; flex-wrap: wrap; }
    .dcals { flex-direction: column; border-left: 0; padding-left: 0; border-top: 1px solid var(--border); padding-top: 10px; }
  }
  .smooth { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-2); font-size: 12.5px; cursor: pointer; }
  .smooth input { accent-color: var(--fm); }
  .axis-note { width: 100%; color: var(--muted); font-size: 11.5px; padding-top: 2px; }

  .overview {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px 12px;
    margin-bottom: 18px;
  }
  .overview h2 { font-size: 15px; font-weight: 600; margin: 0 0 2px; }
  .overview .osub { color: var(--muted); font-size: 11.5px; margin-bottom: 10px; }
  .ocols { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; }
  #msurge, #tqlist { overflow-x: auto; }
  .quad #oquad { display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: flex-start; }
  .quad #oquad svg { flex: 0 1 470px; }
  .quad #oquad .qnote { flex: 1 1 280px; margin-top: 16px; }
  .qhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; }
  .qhead select { font: inherit; font-size: 12px; color: var(--ink-2); background: var(--chip-bg);
    border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px; cursor: pointer; }
  #oscore { overflow-x: auto; }
  .mtab.score { min-width: 640px; }
  .mtab td.why { white-space: normal; }
  .sline { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; font-size: 12.5px; }
  .sline .slabel { color: var(--muted); font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 10.5px;
    text-transform: uppercase; letter-spacing: .04em; margin-right: 4px; }
  details.sline > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline; gap: 8px; width: 100%; }
  details.sline > summary::-webkit-details-marker { display: none; }
  details.sline > summary::before { content: "▸"; color: var(--muted); font-size: 10px; }
  details.sline[open] > summary::before { content: "▾"; }
  .schip { font: inherit; font-size: 12px; font-weight: 600; color: var(--ink); cursor: pointer;
    background: var(--chip-bg); border: 1px solid var(--border); border-radius: 999px; padding: 2px 9px; }
  .schip:hover { border-color: var(--muted); }
  .schip .lbl { color: var(--muted); font-weight: 400; font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 11px; }
  .s-out .schip { border-color: rgba(12,163,12,.45); }
  .ocol h3 {
    font-size: 11px; font-weight: 500; color: var(--muted); margin: 4px 0 4px;
    text-transform: uppercase; letter-spacing: .05em;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
  }
  .pill {
    display: inline-block; border-radius: 999px; padding: 1px 9px;
    font-size: 11px; font-weight: 600; white-space: nowrap;
  }
  .pill.st-out { background: #0ca30c; color: #fff; }
  .pill.st-track { background: var(--chip-bg); color: var(--ink-2); border: 1px solid var(--border); }
  .pill.st-miss { background: #d03b3b; color: #fff; }
  .pill.st-low { color: var(--muted); border: 1px dashed var(--axis); }
  .quad svg { width: 100%; max-width: 470px; height: auto; }
  .quad .dot { cursor: pointer; }
  .quad .dot:hover circle { stroke: var(--ink); stroke-width: 1.5; }
  details.pop { position: relative; }
  details.pop > summary { list-style: none; cursor: pointer; }
  details.pop > summary::-webkit-details-marker { display: none; }
  details.pop .popbody {
    position: absolute; top: calc(100% + 6px); left: 0; z-index: 30;
    display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
    background: var(--tooltip-bg); border: 1px solid var(--border); border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,.14); padding: 10px 12px; min-width: 240px;
  }
  details.pop-r .popbody { left: auto; right: 0; }
  .popbody .prow { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12.5px; color: var(--ink-2); white-space: nowrap; }
  .popbody .prow input[type=range] { width: 96px; accent-color: var(--fire-mk); }
  .popbody .prow b { font-family: "IBM Plex Mono", ui-monospace, monospace; font-weight: 500; color: var(--ink); }
  .popbody select, .impact select { font: inherit; font-size: 12px; color: var(--ink); background: transparent;
    border: 1px solid var(--border); border-radius: 6px; padding: 1px 4px; cursor: pointer; }
  .howto { color: var(--ink-2); font-size: 12px; line-height: 1.55; max-width: 96ch; margin: -8px 0 16px; }
  .howto svg { vertical-align: -1px; }
  .impact select { font: inherit; font-size: 12px; color: var(--ink); background: transparent;
    border: 1px solid var(--border); border-radius: 6px; padding: 1px 4px; cursor: pointer; }
  .overview .qnote, .movers .qnote { color: var(--muted); font-size: 11.5px; margin-top: 6px; max-width: 92ch; }
  .mtab td.stcell { overflow: visible; text-overflow: clip; }
  .mtab td.dim { color: var(--ink-2); }
  .mtab td.bad { color: #d03b3b; font-weight: 600; }
  .omiss { margin-top: 14px; }

  .movers {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px 12px;
    margin-bottom: 18px;
  }
  .movers .mhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }
  .movers .mhead h2 { font-size: 15px; font-weight: 600; margin: 0; }
  .movers .mhead select {
    font: inherit; font-size: 12px; color: var(--ink-2);
    background: var(--chip-bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 2px 6px; cursor: pointer;
  }
  .movers .mhead .mnote { color: var(--muted); font-size: 11.5px; margin-left: auto; }
  .mcols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 26px; margin-top: 8px; }
  @media (max-width: 900px) { .mcols { grid-template-columns: 1fr; } }
  .mcol h3 {
    font-size: 11px; font-weight: 500; color: var(--muted); margin: 4px 0 4px;
    text-transform: uppercase; letter-spacing: .05em;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
  }
  table.mtab { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12.5px; }
  .mtab th {
    color: var(--muted); font-weight: 500; text-align: right; vertical-align: bottom;
    padding: 2px 0 4px 8px; font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 10px; text-transform: uppercase; letter-spacing: .04em;
  }
  .mtab th.l { text-align: left; padding-left: 0; }
  .mtab td {
    border-top: 1px solid var(--grid); padding: 4px 0 4px 8px; text-align: right;
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums;
    color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .mtab td.rk { color: var(--muted); font-size: 11px; text-align: left; padding-left: 0; }
  .mtab td.mn { text-align: left; font-family: inherit; font-weight: 600; padding-left: 0; }
  .mtab td.ab { color: var(--muted); font-size: 10.5px; text-align: left; }
  .mtab td.kw { text-align: left; font-family: inherit; color: var(--ink-2); }
  .mtab tr.mrow { cursor: pointer; }
  .mtab tr.mrow:hover td { background: var(--chip-bg); }
  .mtab tr.mrow:focus-visible { outline: 2px solid var(--fm); outline-offset: -2px; }
  .mtab .up { color: var(--f); font-weight: 600; }
  .mtab .up { color: var(--f); font-weight: 600; }
  .mtab .dn { color: #d03b3b; font-weight: 600; }
  .mtab .lbl { color: var(--muted); font-weight: 400; }
  .mtab .pill { font-size: 10.5px; padding: 1px 7px; }
  .mtab tr.sub td { border-top: 0; padding-top: 1px; padding-bottom: 1px; font-size: 11.5px; color: var(--ink-2); }
  .mtab button.more { font: inherit; font-size: 11px; color: var(--muted); background: none; border: 0;
    padding: 0 2px; cursor: pointer; text-decoration: underline dotted; }
  .mtab button.more:hover { color: var(--ink); }
  .tqtab td.stcell { white-space: normal; text-align: left; }
  .tqtab th:last-child, .tqtab td.stcell { padding-left: 22px; }
  .mtab.surge { min-width: 640px; }
  .mtab.surge th, .mtab.surge td.mn { white-space: normal; line-height: 1.3; }
  #msurge, #tqlist { margin-top: 8px; overflow-x: auto; }
  .mempty { color: var(--muted); font-size: 12px; padding: 6px 2px; }
  .mcol .mempty { color: var(--muted); font-size: 12px; padding: 6px 2px; }

  .grid { display: grid; grid-template-columns: 1fr; gap: 18px; }
  .statef {
    font: inherit; font-size: 12.5px; color: var(--ink); font-weight: 600;
    background: var(--chip-bg); border: 1px solid var(--border); border-radius: 999px;
    padding: 4px 10px; cursor: pointer; margin-right: 4px;
  }
  .statef:focus-visible { outline: 2px solid var(--fm); }
  .mapcard .mtitle { font-size: 13px; font-weight: 600; margin: 0 0 2px; }
  .mapcard .msub { color: var(--muted); font-size: 11.5px; margin-bottom: 8px; }
  .mapcard .mapbox { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-start; }
  .mapcard .mapbox > svg { max-width: 460px; width: 100%; height: auto; flex: 1 1 300px; }
  .mapcard svg path.under { fill: var(--grid); pointer-events: none; }
  .mapcard svg g.fmk { pointer-events: all; cursor: pointer; }
  .mapcard svg path.dma { cursor: pointer; stroke: var(--bg); stroke-width: 0.8; }
  .mapcard svg path.dma:hover { stroke: var(--ink); stroke-width: 1.4; }
  .mapcard svg path.outline { fill: none; stroke: var(--muted); stroke-width: 1.4; pointer-events: none; }
  .maplegend { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--ink-2); min-width: 150px; }
  .maplegend .li { display: flex; align-items: center; gap: 7px; }
  .maplegend .li svg { width: 22px; height: 12px; flex: none; }
  .maplegend .swb { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  .chart { margin-top: 8px; }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px 8px;
    min-width: 0;
  }
  .card h2 { font-size: 15px; font-weight: 600; margin: 0; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .card h2 .ab { color: var(--muted); font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 11px; font-weight: 500; }
  .card h2 .notraffic { color: var(--muted); font-size: 11.5px; font-weight: 400; border: 1px dashed var(--axis); border-radius: 999px; padding: 1px 9px; }
  .card h2 .msel {
    margin-left: auto; font: inherit; font-size: 12px; color: var(--ink-2);
    background: var(--chip-bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 2px 6px; cursor: pointer;
  }
  .card h2 .msel:focus-visible { outline: 2px solid var(--fm); }
  .stats { display: flex; flex-wrap: wrap; gap: 4px 18px; margin: 6px 0 4px; color: var(--ink-2); font-size: 12px; }
  .stats b { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
  .stats .lbl { color: var(--muted); }
  .stats .pages { cursor: help; text-decoration: underline dotted var(--axis); text-underline-offset: 3px; }
  .stats .modestats { display: contents; }
  .stats .pill { font-size: 11px; }
  .stats .up { color: var(--f); font-weight: 600; }
  .stats .dn { color: #d03b3b; font-weight: 600; }
  .chart { position: relative; }
  .chart svg { display: block; width: 100%; height: auto; }
  details.tbl { margin: 2px 0 6px; }
  details.tbl summary { color: var(--muted); font-size: 12px; cursor: pointer; padding: 4px 0; }
  details.tbl summary:hover { color: var(--ink-2); }
  .tblwrap { max-height: 300px; overflow: auto; border: 1px solid var(--border); border-radius: 6px; }
  table { border-collapse: collapse; width: 100%; font-size: 11.5px; font-family: "IBM Plex Mono", ui-monospace, monospace; }
  th, td { text-align: right; padding: 3px 8px; border-bottom: 1px solid var(--grid); white-space: nowrap; font-variant-numeric: tabular-nums; }
  th { position: sticky; top: 0; background: var(--surface); color: var(--muted); font-weight: 500; }
  th:first-child, td:first-child { text-align: left; }

  #tip {
    position: fixed; pointer-events: none; z-index: 20; display: none;
    background: var(--tooltip-bg); border: 1px solid var(--border); border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,.14);
    padding: 8px 10px; font-size: 12px; min-width: 190px;
  }
  #tip .d { font-weight: 600; margin-bottom: 5px; }
  #tip .d .pill { font-size: 10.5px; padding: 0 7px; margin-left: 6px; vertical-align: 1px; }
  #tip .tnote { color: var(--muted); font-size: 11px; margin-top: 4px; }
  #tip .d .lbl { color: var(--muted); font-weight: 400; margin-left: 4px; }
  #tip .row { display: flex; align-items: center; gap: 7px; justify-content: space-between; color: var(--ink-2); padding: 1px 0; }
  #tip .row .v { font-family: "IBM Plex Mono", ui-monospace, monospace; color: var(--ink); font-variant-numeric: tabular-nums; }
  #tip .row .n { display: inline-flex; align-items: center; gap: 6px; max-width: 300px; overflow-wrap: anywhere; }
  #tip { max-width: 420px; }
  #tip table.tt { border-collapse: collapse; }
  #tip table.tt th {
    color: var(--muted); font-weight: 500; text-align: right; padding: 0 0 4px 12px;
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 10px;
    text-transform: uppercase; letter-spacing: .05em;
  }
  #tip table.tt th:first-child { text-align: left; padding-left: 0; }
  #tip table.tt td {
    padding: 1.5px 0 1.5px 12px; text-align: right; white-space: nowrap;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-variant-numeric: tabular-nums; color: var(--ink); font-size: 12px;
  }
  #tip table.tt td.n {
    text-align: left; padding-left: 0; color: var(--ink-2);
    font-family: inherit; font-variant-numeric: normal;
  }
  #tip table.tt td.n span.sw { display: inline-flex; vertical-align: -1px; margin-right: 6px; }
  #tip table.tt .pos { color: var(--f); }
  #tip table.tt .zero { color: var(--muted); }

  footer.notes { margin-top: 26px; color: var(--muted); font-size: 12px; max-width: 88ch; }
  footer.notes p { margin: 4px 0; }
</style>

<div class="wrap">
  <header class="page">
    <h1>Wildfire Demand Overlay</h1>
    <span class="meta" id="meta"></span>
  </header>
  <p class="sub">Google search interest for fire keywords vs. daily unique users on this
  site's state &amp; incident pages (each state's total = its state page + all its fire pages).
  Every series is indexed so timing and shape line up: <b>100&nbsp;= that area's peak in the window</b>
  (Search Console position and CTR use their own units on the right-hand axis).
  Search interest is measured in-state (queries from within the state), or per metro via the dropdown on each card.
  Hover any chart for exact values; raw user counts are in the tooltip and tables.</p>

  <div class="controls" id="controls"></div>
  <div class="howto" id="howto" hidden></div>
  <section class="overview" id="overview" hidden>
    <h2>Overview — SEO health</h2>
    <div class="osub" id="osub"></div>
    <div class="ocols">
      <div class="ocol"><h3>Where we're missing search demand</h3><div id="oscore"></div></div>
      <div class="ocol quad"><div class="qhead"><h3 id="oqtitle">Compare two lifts</h3>
        <select id="qpreset" aria-label="Which two lifts to compare"></select></div><div id="oquad"></div></div>
    </div>
  </section>
  <section class="movers" id="movers" hidden>
    <div class="mhead">
      <h2>Metros surging now</h2>
      <select id="mkw" aria-label="Search term"></select>
      <span class="mnote" id="mnote"></span>
    </div>
    <div id="msurge"></div>
    <div class="qnote">Metros where a search term averaged at least 1.5× last week's level this week (and at least 5 on
    the metro's own index) — and whether our visitors from there rose with it. Both weeks come from the most recent
    stretch Google Trends reports consistently. Click a row to open that metro's chart.</div>
  </section>
  <section class="movers" id="tq" hidden>
    <div class="mhead">
      <h2>Top search opportunities</h2>
      <span class="mnote" id="tqnote"></span>
    </div>
    <div id="tqlist"></div>
    <div class="qnote">One row per page on our site (usually one fire), ranked by <b>extra clicks / week</b>: the clicks
    its queries would get at the click-through rate this site normally earns at their position (or at position 5 for
    queries below page 1), minus the clicks they actually got. <b>page 2+</b> = most of the gap is queries ranking below
    the first page · <b>weak snippet</b> = we rank on page 1 but get fewer clicks than usual for that position ·
    <b>new demand</b> = the page had no impressions two weeks earlier · <b>old page</b> = traffic landing on a fire more
    than 90 days old. Expand a row for its queries; click to open the state.</div>
  </section>
  <div class="grid" id="grid"></div>

  <footer class="notes">
    <p><b>Method.</b> Site traffic is pulled from the PostHog API at build time — the header shows when. State and
    metro totals are true daily uniques (a person visiting several of a state's pages in one day counts once); the
    per-page list (hover the organic number on a card) counts a person once per page visited, so pages can sum to more
    than the total. Search demand is Google Trends daily interest, measured <b>in-state</b> (queries made from within
    the state itself, geo US-XX) or per metro. Keywords: wildfire {state}, fire {state}, fire {abbr}, "fire near me",
    and in metro view "fire near {city}" (the metro's biggest city). Each area's keywords come from one Google Trends
    request, so they share one scale — the area's best term-day = 100 — and are directly comparable within an area,
    but not across areas. When Google Trends returns zeros for many metros on the same day (unprocessed recent days),
    those metro-days are treated as missing rather than as zero.</p>
    <p><b>SEO health (Overview and card headers).</b> Everything that judges health uses the last 14 days.
    <b>Search</b> = the average of an area's keyword indices over those days as a multiple of its typical (median) day;
    <b>us</b> = the same for our organic visits (search-engine referrers: Google, Bing, DuckDuckGo, Yahoo, Ecosia, Brave).
    Status comes from us ÷ search, whether search rose or fell: below 0.6× = missing demand (our traffic fell behind search),
    above 1.25× = outperforming, otherwise tracking. <b>Est. missed visits/wk</b> = (search multiple − our multiple) × our
    typical day × 7. <b>Likely why</b> reads Search Console over the same stretch: "losing visibility" = impressions
    didn't keep up with search (a ranking or indexing gap); "shown, not clicked" = impressions rose but clicks didn't
    (a title/snippet or position gap); "Google clicks kept pace" = the shortfall is outside Google search.
    <b>Can't judge yet:</b> Google Trends reports low-volume days as zero except for the most recent ~14 days of each
    request, so for states whose search history is mostly zero there is no reliable typical level — those states are
    held back rather than given a misleading multiple. A 14-day window halves how often a status flips on noise compared
    with 7 days, while a real surge still registers the day after it starts. The quadrant plots any two of these
    multiples on log axes, capped at 24× (states past the cap are drawn scaled down along their own ray, so they stay on
    the correct side of the diagonal).</p>
    <p><b>Chart dates.</b> The date button at the top sets the window every state chart shows: the last 7, 14, 30 or 90
    days, all data, or any start and end day picked on its two calendars. The health tables, surge list and opportunities
    keep their own fixed windows. The left axis rescales to the largest value visible in the chosen dates, but index
    values don't change when you pick dates: traffic and Search Console impressions stay indexed to their own peak over
    the whole window, and the search terms share one Google Trends scale per area (100 = the busiest term-day). Search
    Console average position and CTR are plotted on the right-hand axis in their own units, sharing the left axis'
    gridlines; position is inverted (1 = top result at the top). With 7-day smoothing on, both are impression-weighted
    over the 7 days.</p>
    <p><b>Metro view.</b> The dropdown on a state card narrows both series to one metro area: site traffic counts only
    visitors whose GeoIP location is within 50 miles of the metro's biggest city (still viewing that state's pages), and
    search interest is fetched for the metro's own Google Trends market (Nielsen DMA, e.g. geo US-OR-820 for Portland).
    A state's dropdown lists every DMA Google files under that state — cross-border markets (Denver appears under
    Nebraska and Wyoming too) use that state's keywords, capturing spillover audiences.</p>
    <p><b>Search Console.</b> Impressions, clicks, CTR and average position come from the Google Search Console API
    for the https://fires.cornea.is/ property (web search; image, video and news are under 1% of web), synced daily on
    the maintainer's machine — the last 7 days are re-fetched every run, so Google's revisions and missed days are picked
    up. State series use page-level totals, which are complete; Google withholds rare queries whenever query text is
    requested (about half of impressions here), so query-based views — metro slices and Top search opportunities — cover
    only the queries Google discloses. CTR is recomputed from summed clicks and impressions; average position is
    impression-weighted (1 = the top result). Data lags about two days.</p>
    <p><b>Top search opportunities.</b> Queries from the last 14 complete Search Console days, grouped by the page they
    land on (brand and homepage searches excluded). <b>Potential clicks</b> = for each page, the clicks its queries would
    have earned at this site's usual click-through rate for their position (for queries below page 1, at position 5),
    minus the clicks they actually got; shown per week, pages under 3/week left out. The usual click-through rate by
    position is fitted from this site's last 28 days. Queries that drew thousands of impressions but never a single
    click — where real searchers would have produced 10 or more — are treated as automated traffic and excluded.
    Page impressions and their trend are the page's complete Search Console totals.</p>
    <p><b>Metros surging now.</b> For each metro, the term whose average this week is highest relative to last week,
    counting only terms averaging at least 5 on the metro's own 0–100 index; shown when this week is 1.5× last week or
    more (each market listed once). Both weeks come from the most recent stretch that Google Trends reports consistently.
    <b>Capturing</b> = our visitors from that metro this week averaged at least 1.5× last week's.</p>
    <p><b>Fire milestones.</b> Yellow diamonds straddling the baseline mark wildfire start dates in that state, sourced from the
    fire API (fire-api-dev.web.app): wildfires only (prescribed burns excluded), &gt;100 acres final size, started within
    the window. A small number above a triangle counts multiple starts that day; hover the chart to see fire names,
    acreage, and nearby population. A diamond's center sits on the fire's start date. Start date = the fire's
    created-on date (UTC).</p>
    <p><b>Impactful fires.</b> A fire is impactful when at least P people live within R miles of its start point —
    both configurable with the sliders (default 2k within 5 mi). Distance is measured from the fire's approximate
    edge: R plus the fire's own radius if its final acreage were a circle (√(acres⁄640π) miles — adds ~7 mi for a
    100k-acre fire, ~0 for a 100-acre fire). Population = 2020 Census block-group centroids (national file, so state
    borders don't clip counts). Solid diamond = impactful at the current thresholds, hollow = not; a day with several
    fires shows solid if any qualifies. Block-group resolution makes counts step-shaped under ~2 miles, so the radius
    slider starts at 2 mi.</p>
    <p><b>Caveats.</b> Site traffic is indexed to its own peak — compare timing/shape against search, not absolute level.
    Abbreviation terms can be ambiguous to Google ("fire or", "fire co", "fire id" catch unrelated queries), which inflates their baselines.
    A keyword line flat at zero means search volume stayed below Google's reporting threshold all window — not missing data
    (state-restricted volumes are smaller, so this happens more often in in-state mode).
    The final day of the window is partial in Google's data.</p>
  </footer>
</div>
<div id="tip" role="status"></div>

<script>
const DATA = __DATA__;

/* keyword template slots: hue by template, dash for abbreviation variant */
const KW_META = [
  { tpl: "wildfire",  varr: "name", color: "var(--wf)", dash: null },
  { tpl: "fire",      varr: "name", color: "var(--f)",  dash: null },
  { tpl: "fire",      varr: "abbr", color: "var(--f)",  dash: "6 4" },
  { tpl: "fire near", varr: "me",   color: "var(--fn)", dash: null },
  { tpl: "fire near", varr: "city", color: "var(--fn)", dash: "6 4" },  /* metro view only */
];
/* "wildfire {state}" (zero on ~95% of days) and "fire near me" start hidden under "more terms" */
const visible = { traffic: true, k0: false, k1: true, k2: true, k3: false, k4: true, fires: true, gi: true, gpos: true, gctr: false };
let smooth = false;
let y25 = false;
let mode = "state";
const GSC = DATA.gsc;
const GSC_LABEL = { web: "Web", image: "Image", video: "Video", news: "News tab", discover: "Discover", googleNews: "Google News" };
const gscType = "web";   /* image/video/news are <1% of web impressions */
const MODE_LABEL = { state: "in-state", national: "national" };
const MODE_GEO = { state: "geo US-XX (in-state)", national: "geo US (national)" };

const fmt = n => n >= 1e6 ? (n/1e6).toFixed(1)+"M" : n >= 10000 ? Math.round(n/1000)+"k" : n >= 1000 ? (n/1000).toFixed(1)+"k" : String(Math.round(n));
const POP_STEPS = [100, 250, 500, 750, 1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000, 25000, 50000, 100000];
const RING_STEPS = ["2", "3", "5", "7.5", "10", "15", "20"];
const impact = { pop: 2000, ring: "5" };
const isImpactful = f => !!(f.p && f.p[impact.ring] >= impact.pop);
const fdate = d => { const [y,m,dd] = d.split("-"); return new Date(+y, m-1, +dd).toLocaleDateString(undefined, {month:"short", day:"numeric"}); };
const fdateY = d => { const [y,m,dd] = d.split("-"); return new Date(+y, m-1, +dd).toLocaleDateString(undefined, {month:"short", day:"numeric", year:"numeric"}); };
const kwOf = st => (st.modes[mode] && st.modes[mode].kwSeries) || null;
/* view = what the card currently shows: whole state (sel=null) or one metro */
function selOf(card, st) {
  const mi = +(card.dataset.msel ?? -1);
  return (mi >= 0 && st.metros && st.metros[mi]) || null;
}
function viewOf(st, sel) {
  if (sel) return {
    traf: sel.traffic,
    kwS: (sel.mode && sel.mode.kwSeries) || null,
    kws: sel.kws || st.kws,
    k25: null,
    label: sel.name + " metro",
  };
  return {
    traf: st.traffic,
    kwS: kwOf(st),
    kws: st.kws,
    k25: (y25 && st.modes[mode] && st.modes[mode].kw25) || null,
    label: MODE_LABEL[mode],
  };
}

function smooth7(s) {
  const out = new Array(s.length);
  for (let i = 0; i < s.length; i++) {
    let a = Math.max(0, i-3), b = Math.min(s.length-1, i+3), sum = 0;
    for (let j = a; j <= b; j++) sum += s[j];
    out[i] = sum / (b - a + 1);
  }
  return out;
}

/* null-aware helpers for Search Console series (null = day not available) */
function smooth7n(s) {
  return s.map((v, i) => {
    if (v == null) return null;
    let sum = 0, n = 0;
    for (let j = Math.max(0, i - 3); j <= Math.min(s.length - 1, i + 3); j++) if (s[j] != null) { sum += s[j]; n++; }
    return sum / n;
  });
}
function idxOf(s) {
  let mx = 0;
  s.forEach(v => { if (v != null && v > mx) mx = v; });
  return s.map(v => v == null ? null : (mx ? v / mx * 100 : 0));
}
function gscOf(st, sel) {
  const src = sel ? sel.gsc : st.gsc;
  return (src && src[gscType]) || null;
}
const fpct = v => v == null ? "–" : (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%";
const fposn = v => v == null ? "–" : v.toFixed(1);

/* ---------- controls / legend ---------- */
function legendSwatch(meta) {
  if (meta === "traffic")
    return '<svg width="22" height="12" aria-hidden="true"><rect x="1" y="4" width="20" height="7" rx="1.5" fill="var(--traffic-fill)"/><line x1="1" y1="4" x2="21" y2="4" stroke="var(--traffic)" stroke-width="2"/></svg>';
  if (meta === "fires")
    return '<svg width="22" height="12" aria-hidden="true"><path d="M11 1.5 L15 6 L11 10.5 L7 6 Z" fill="var(--fire-mk)" stroke="var(--ink-2)" stroke-width="0.6"/></svg>';
  if (meta === "fires_h")
    return '<svg width="22" height="12" aria-hidden="true"><path d="M11 2 L14.5 6 L11 10 L7.5 6 Z" fill="none" stroke="var(--fire-mk)" stroke-width="1.4"/></svg>';
  return `<svg width="22" height="12" aria-hidden="true"><line x1="2" y1="6" x2="20" y2="6" stroke="${meta.color}" stroke-width="2.4"${meta.dash ? ` stroke-dasharray="${meta.dash}"` : ""}${meta.cap ? ` stroke-linecap="round"` : ""}/></svg>`;
}
let stateFilter = "-1";
function chip(k, sw, label) {
  const on = k.split(",").every(x => visible[x]);
  return `<button class="lg${on ? "" : " off"}" data-k="${k}" aria-pressed="${on}">${sw}<span class="sw">${label}</span></button>`;
}
function buildControls() {
  const c = document.getElementById("controls");
  const both = `<svg width="22" height="12" aria-hidden="true"><line x1="1" y1="3.5" x2="21" y2="3.5" stroke="var(--f)" stroke-width="2"/><line x1="1" y1="8.5" x2="21" y2="8.5" stroke="var(--f)" stroke-width="2" stroke-dasharray="4 3"/></svg>`;
  let html = `<select class="statef" id="statef" aria-label="State filter"><option value="-1">All states</option>` +
    DATA.states.map(st => `<option value="${st.key}">${st.name}</option>`).join("") + `</select>`;
  html += `<details class="pop dpick" id="dpick"><summary class="lg dbtn" title="Dates shown on every state chart">
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="1.5" y="2.5" width="11" height="10" rx="1.5"/><line x1="1.5" y1="5.6" x2="12.5" y2="5.6"/><line x1="4.5" y1="1" x2="4.5" y2="3.8"/><line x1="9.5" y1="1" x2="9.5" y2="3.8"/></svg>
      <span id="dlabel"></span> ▾</summary>
    <div class="popbody dpbody">
      <div class="dpresets" role="group" aria-label="Date presets">` +
      RANGE_PRESETS.map(([k, l]) => `<button type="button" data-p="${k}" aria-pressed="false">${l}</button>`).join("") + `</div>
      <div class="dcals"><div class="dcal" id="dcal-start"></div><div class="dcal" id="dcal-end"></div></div>
    </div></details>`;
  html += `<span class="gap"></span>`;
  html += `<label class="smooth"><input type="checkbox" id="sm"> 7-day smooth</label>`;
  html += `<details class="pop pop-r"><summary class="lg">⚙ settings</summary><div class="popbody">
      <div class="prow" title="A fire is impactful when at least this many people (2020 Census) live within this distance of its start point, measured from the fire's approximate edge">
        ${legendSwatch("fires")} impactful fire ≥
        <input type="range" id="ipop" min="0" max="${POP_STEPS.length - 1}" step="1" value="${POP_STEPS.indexOf(impact.pop)}" aria-label="Impactful population threshold">
        <b id="ipopv">2k</b> people within
        <input type="range" id="irad" min="0" max="${RING_STEPS.length - 1}" step="1" value="${RING_STEPS.indexOf(impact.ring)}" aria-label="Impactful radius">
        <b id="iradv">5 mi</b></div>
    </div></details>`;
  html += `<button class="lg" id="howtoBtn" aria-expanded="false">ⓘ how to read</button>`;
  html += `<span class="cbreak"></span>`;
  html += chip("traffic", legendSwatch("traffic"), "our traffic");
  html += chip("k1,k2", both, `fire <span style="color:var(--muted)">{state / abbr}</span>`);
  html += chip("fires", legendSwatch("fires"), "fire starts");
  if (GSC) {
    html += chip("gi", legendSwatch({ color: "var(--gi)" }), "GSC impressions");
    html += chip("gpos", legendSwatch({ color: "var(--gp)", dash: "0.1 3.6", cap: true }), `GSC avg position <span style="color:var(--muted)">· right axis</span>`);
    html += chip("gctr", legendSwatch({ color: "var(--gc)" }), `GSC CTR <span style="color:var(--muted)">· right axis</span>`);
  }
  html += `<details class="pop"><summary class="lg">more terms ▾</summary><div class="popbody">
      ${chip("k0", legendSwatch(KW_META[0]), `wildfire <span style="color:var(--muted)">{state}</span>`)}
      ${chip("k3", legendSwatch(KW_META[3]), "fire near me")}
      ${chip("k4", legendSwatch(KW_META[4]), `fire near <span style="color:var(--muted)">{city} · metro view</span>`)}
    </div></details>`;
  c.innerHTML = html;

  document.getElementById("howto").innerHTML = `Every line is indexed so shapes line up: 100 = that series' peak in the window.
    Search terms are in-state Google Trends (searches made from within the state); pick a metro on a card for metro-level data.
    The green chip draws "fire {state}" solid and the two-letter abbreviation dashed. Search Console impressions (pink) are indexed
    the same way. Search Console average position (dotted) and CTR (blue) are drawn in their own units on the right-hand axis;
    position is inverted so 1, the top result, sits at the top. Search Console lags about two days.
    The date button at the top sets the window every state chart shows.
    In a metro view, Search Console covers queries that mention the metro's biggest city. Fire markers: ${legendSwatch("fires")} = impactful
    under the current settings, ${legendSwatch("fires_h")} = not. Full definitions are in the notes at the bottom of the page.`;
  document.getElementById("howtoBtn").addEventListener("click", e => {
    const h = document.getElementById("howto");
    h.hidden = !h.hidden;
    e.currentTarget.setAttribute("aria-expanded", String(!h.hidden));
  });
  /* composedPath: a click that re-renders the popover (month arrows) must not count as "outside" */
  document.addEventListener("click", e => {
    const path = e.composedPath();
    document.querySelectorAll("details.pop[open]").forEach(d => { if (!path.includes(d)) d.open = false; });
  });
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.pop[open]").forEach(d => { d.open = false; d.querySelector("summary").focus(); });
  });
  /* keep jump-to-card targets clear of the sticky bar */
  const setCtrlH = () => document.documentElement.style.setProperty("--ctrl-h",
    (getComputedStyle(c).position === "sticky" ? c.offsetHeight : 0) + "px");
  if (window.ResizeObserver) new ResizeObserver(setCtrlH).observe(c);
  setCtrlH();
  document.getElementById("statef").addEventListener("change", e => {
    stateFilter = e.target.value;
    applyStateFilter();
  });
  c.querySelectorAll(".lg[data-k]").forEach(btn => btn.addEventListener("click", () => {
    const ks = btn.dataset.k.split(",");
    const on = !ks.every(k => visible[k]);
    ks.forEach(k => { visible[k] = on; });
    btn.classList.toggle("off", !on);
    btn.setAttribute("aria-pressed", String(on));
    renderAll();
  }));
  document.getElementById("sm").addEventListener("change", e => { smooth = e.target.checked; renderAll(); });
  /* ---- chart dates: presets + a start calendar and an end calendar ---- */
  const dpick = document.getElementById("dpick");
  const D0 = DATA.dates[0], D1 = DATA.dates[N - 1];
  const ymd = (y, m, d) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const monthOf = iso => { const [y, m] = iso.split("-"); return { y: +y, m: +m - 1 }; };
  const calView = {};
  const presetOf = () => range.r1 !== N - 1 ? "custom" : range.r0 === 0 ? "all"
    : (RANGE_PRESETS.find(([k]) => k !== "all" && N - +k === range.r0) || ["custom"])[0];
  function renderCal(which) {
    const el = document.getElementById("dcal-" + which), v = calView[which];
    const first = new Date(v.y, v.m, 1), days = new Date(v.y, v.m + 1, 0).getDate();
    const s0 = DATA.dates[range.r0], s1 = DATA.dates[range.r1], picked = which === "start" ? s0 : s1;
    const canPrev = ymd(v.y, v.m, 1) > D0, canNext = ymd(v.y, v.m, days) < D1;
    let h = `<div class="dchead">${which === "start" ? "Start" : "End"} <b>${fdateY(picked)}</b></div>
      <div class="dcnav"><button type="button" class="dnav" data-dir="-1" aria-label="Previous month"${canPrev ? "" : " disabled"}>‹</button>
      <span>${first.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</span>
      <button type="button" class="dnav" data-dir="1" aria-label="Next month"${canNext ? "" : " disabled"}>›</button></div>
      <div class="dgrid">` + ["S", "M", "T", "W", "T", "F", "S"].map(d => `<span class="dow" aria-hidden="true">${d}</span>`).join("");
    for (let k = 0; k < first.getDay(); k++) h += `<span></span>`;
    for (let d = 1; d <= days; d++) {
      const iso = ymd(v.y, v.m, d);
      const cls = [iso === picked ? "pick" : "", iso >= s0 && iso <= s1 ? "in" : "", iso === s0 ? "rs" : "", iso === s1 ? "re" : ""].filter(Boolean).join(" ");
      h += `<button type="button" class="dday ${cls}" data-d="${iso}"${iso < D0 || iso > D1 ? " disabled" : ""}
        aria-label="${which} date ${fdateY(iso)}" aria-pressed="${iso === picked}">${d}</button>`;
    }
    el.innerHTML = h + `</div>`;
  }
  const syncRange = (resetViews = true) => {
    range.preset = presetOf();
    const pl = (RANGE_PRESETS.find(([k]) => k === range.preset) || [])[1];
    document.getElementById("dlabel").innerHTML = pl ? `${pl} <span class="lbl">· ${rangeText()}</span>` : rangeText();
    dpick.querySelectorAll("[data-p]").forEach(b => {
      const on = b.dataset.p === range.preset;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    if (resetViews || !calView.start) { calView.start = monthOf(DATA.dates[range.r0]); calView.end = monthOf(DATA.dates[range.r1]); }
    renderCal("start"); renderCal("end");
    try { localStorage.setItem("wdo-chart-range", JSON.stringify(range.preset === "custom"
      ? { p: "custom", from: DATA.dates[range.r0], to: DATA.dates[range.r1] } : { p: range.preset })); } catch (e) {}
  };
  /* first index on or after a YYYY-MM-DD date */
  const idxAt = d => { const i = DATA.dates.findIndex(x => x >= d); return i < 0 ? N - 1 : i; };
  try {
    const saved = JSON.parse(localStorage.getItem("wdo-chart-range") || "null");
    if (saved && saved.p === "custom" && saved.from && saved.to) {
      const [a, b] = saved.from <= saved.to ? [saved.from, saved.to] : [saved.to, saved.from];
      if (b >= D0 && a <= D1) setRange("custom", idxAt(a), idxAt(b));   /* ignore a range the data has moved past */
    } else if (saved && RANGE_PRESETS.some(([k]) => k === saved.p)) setRange(saved.p);
  } catch (e) {}
  syncRange();
  dpick.querySelector(".dpbody").addEventListener("click", e => {
    const pr = e.target.closest("[data-p]"), nav = e.target.closest(".dnav"), day = e.target.closest(".dday");
    if (pr) { setRange(pr.dataset.p); syncRange(); renderAll(); dpick.open = false; return; }
    if (nav && !nav.disabled) {
      const which = nav.closest(".dcal").id.slice(5), v = calView[which];
      const d = new Date(v.y, v.m + +nav.dataset.dir, 1);
      calView[which] = { y: d.getFullYear(), m: d.getMonth() };
      renderCal(which);
      return;
    }
    if (day && !day.disabled) {
      /* move the picked end; if it crosses the other end, carry that one along to keep the span */
      const which = day.closest(".dcal").id.slice(5), i = DIDX[day.dataset.d], span = range.r1 - range.r0;
      if (which === "start") setRange("custom", i, i < range.r1 ? range.r1 : i + span);
      else setRange("custom", i > range.r0 ? range.r0 : i - span, i);
      syncRange(false); renderAll();
      const again = dpick.querySelector(`#dcal-${which} .dday[data-d="${DATA.dates[which === "start" ? range.r0 : range.r1]}"]`);
      if (again) again.focus();
    }
  });
  let raf = 0;
  const queueRender = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; renderAll(); }); };
  document.getElementById("ipop").addEventListener("input", e => {
    impact.pop = POP_STEPS[+e.target.value];
    document.getElementById("ipopv").textContent = fmt(impact.pop);
    queueRender();
  });
  document.getElementById("irad").addEventListener("input", e => {
    impact.ring = RING_STEPS[+e.target.value];
    document.getElementById("iradv").textContent = impact.ring + " mi";
    queueRender();
  });
}

/* ---------- chart ---------- */
const N = DATA.dates.length;
const ML = 38, MT = 22, MB = 22, RAX = 42;   /* RAX = width of each right-hand axis column */
const DIDX = {};
DATA.dates.forEach((d, i) => DIDX[d] = i);
/* last complete Search Console day on the dashboard axis */
const GSC_LAST = !GSC ? null
  : DIDX[GSC.lastComplete] !== undefined ? DIDX[GSC.lastComplete]
  : GSC.lastComplete > DATA.dates[N - 1] ? N - 1 : null;
function fireMap(st) {
  if (!st._fmap) {
    st._fmap = {};
    (st.fires || []).forEach(f => {
      const i = DIDX[f.d];
      if (i !== undefined) (st._fmap[i] = st._fmap[i] || []).push(f);
    });
  }
  return st._fmap;
}

/* one date range for every state chart, set from the bar at the top */
const RANGE_PRESETS = [["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["all", "All data"]];
const range = { preset: "90", r0: 0, r1: N - 1 };
function setRange(preset, r0, r1) {
  range.preset = preset;
  if (preset !== "custom") { r1 = N - 1; r0 = preset === "all" ? 0 : N - +preset; }
  r0 = Math.max(0, Math.min(N - 2, r0));
  r1 = Math.max(r0 + 1, Math.min(N - 1, r1));   /* at least two days so the x-axis has a span */
  range.r0 = r0; range.r1 = r1;
}
setRange("90");
const rangeText = () => `${fdate(DATA.dates[range.r0])} – ${fdate(DATA.dates[range.r1])}`;

/* right-hand axes: Search Console avg position and CTR in their own units */
const rightAxes = () => GSC ? ["gpos", "gctr"].filter(k => visible[k]) : [];
/* every card is the same width, so one geometry serves all charts (and keeps their x-axes aligned) */
function chartGeom() {
  const grid = document.getElementById("grid");
  const w = Math.max(300, Math.round((grid && grid.clientWidth ? grid.clientWidth : 900) - 34));
  const h = w < 560 ? 210 : 260;
  const nr = rightAxes().length;
  const mr = nr ? 6 + RAX * nr : 12;
  return { w, h, mr, iw: w - ML - mr, ih: h - MT - MB };
}
/* impression-weighted daily (or centered 7-day) Search Console ratio: "pos" or "ctr" (in %) */
function gscRatio(gs, kind) {
  return DATA.dates.map((_, i) => {
    if (gs.i[i] == null) return null;
    const a = smooth ? Math.max(0, i - 3) : i, b = smooth ? Math.min(N - 1, i + 3) : i;
    let num = 0, den = 0;
    for (let j = a; j <= b; j++) {
      if (!gs.i[j]) continue;
      if (kind === "ctr") { num += gs.c[j]; den += gs.i[j]; }
      else if (gs.p[j] != null) { num += gs.p[j] * gs.i[j]; den += gs.i[j]; }
    }
    return den ? (kind === "ctr" ? num / den * 100 : num / den) : null;
  });
}
const stepUp = (raw, steps) => steps.find(s => s >= raw - 1e-9) || steps[steps.length - 1] * Math.ceil(raw / steps[steps.length - 1]);

function niceAxis(rawMax) {
  if (!(rawMax > 0)) rawMax = 100;
  const pow = Math.pow(10, Math.floor(Math.log10(rawMax / 4)));
  let step = 10 * pow;
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (rawMax / (m * pow) <= 4.5) { step = m * pow; break; }
  }
  return { step, ymax: Math.ceil(rawMax / step) * step };
}

/* x-axis labels sized to the range: days, every other day, Mondays (1/2/4-weekly) or months,
   whichever is the finest that fits */
function xTicks(r0, r1, iw) {
  const span = r1 - r0, maxL = Math.max(2, Math.floor(iw / 58)), out = [];
  const dt = i => { const [y, m, d] = DATA.dates[i].split("-"); return new Date(+y, m - 1, +d); };
  const lab = i => dt(i).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (span + 1 <= maxL) { for (let i = r0; i <= r1; i++) out.push([i, lab(i), "middle"]); return out; }
  if (span <= 31 && Math.floor(span / 2) + 1 <= maxL) { for (let i = r1; i >= r0; i -= 2) out.unshift([i, lab(i), "middle"]); return out; }
  const wk = span <= 120 && [7, 14, 28].find(e => Math.floor(span / e) + 1 <= maxL);
  if (wk) {
    let mondays = 0;
    for (let i = r0; i <= r1; i++) if (dt(i).getDay() === 1 && mondays++ % (wk / 7) === 0) out.push([i, lab(i), "middle"]);
    return out;
  }
  const every = [1, 2, 3, 6].find(e => Math.floor(span / 30.44 / e) + 1 <= maxL) || 12;
  for (let i = r0; i <= r1; i++) {
    const d = dt(i);
    /* month names start at the 1st; drop one that would run past the right edge */
    if (d.getDate() === 1 && d.getMonth() % every === 0 && (i - r0) / span * iw < iw - 22)
      out.push([i, d.toLocaleDateString(undefined, { month: "short" }), "start"]);
  }
  return out;
}

function renderChart(st, sel, G) {
  const { r0, r1 } = range;
  const { w, h, mr, iw, ih } = G;
  const Xr = i => ML + ((i - r0) / (r1 - r0)) * iw;
  const { traf, kwS, k25 } = viewOf(st, sel);
  const hasTraffic = !!traf;
  const trafMax = hasTraffic ? Math.max(...traf, 1) : 1;
  const trafIdx = hasTraffic ? traf.map(v => v / trafMax * 100) : null;
  const disp = s => smooth ? smooth7(s) : s;
  const dispN = s => smooth ? smooth7n(s) : s;
  const mono = `font-family="IBM Plex Mono, monospace"`;

  /* left axis: indexed series, fitted to what's visible in the range */
  let rawMax = 0;
  const scan = s => { for (let i = r0; i <= r1; i++) if (s[i] != null && s[i] > rawMax) rawMax = s[i]; };
  if (visible.traffic && hasTraffic) scan(disp(trafIdx));
  if (kwS) kwS.forEach((s, i) => { if (visible["k"+i] && s.length) scan(dispN(s)); });
  if (k25) k25.forEach((s, i) => { if (visible["k"+i] && s.length) scan(disp(s)); });
  const gs = gscOf(st, sel);
  const gLines = gs && visible.gi ? [["gi", dispN(idxOf(gs.i)), "var(--gi)"]] : [];
  gLines.forEach(([, s]) => scan(s));
  const { step, ymax } = niceAxis(rawMax);
  const nGrid = Math.round(ymax / step);
  const Y = v => MT + ih - (v / ymax) * ih;

  /* right axes share the left axis' gridlines: same number of steps, their own nice step size */
  const rAxes = rightAxes().map((k, ai) => {
    const series = gs ? gscRatio(gs, k === "gpos" ? "pos" : "ctr") : null;
    const vals = series ? series.slice(r0, r1 + 1).filter(v => v != null) : [];
    const ax = { k, series, x: w - mr + 8 + ai * RAX, has: vals.length > 0 };
    if (k === "gpos") {      /* inverted: 1 = top result at the top */
      const hi = vals.length ? Math.max(...vals) : 1;
      ax.step = stepUp(Math.max(0, hi - 1) / nGrid, [1, 2, 3, 4, 5, 10, 15, 20, 25, 50, 100]);
      ax.Y = v => MT + (v - 1) / (ax.step * nGrid) * ih;
      ax.tick = kk => String(1 + kk * ax.step);
      ax.color = "var(--gp)"; ax.title = "pos";
    } else {
      ax.step = stepUp(vals.length ? Math.max(...vals) / nGrid : 0, [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50]);
      ax.Y = v => MT + ih - v / (ax.step * nGrid) * ih;
      ax.tick = kk => String(+(kk * ax.step).toFixed(2)) + "%";
      ax.color = "var(--gc)"; ax.title = "CTR";
    }
    return ax;
  });

  const pathOf = (series, Yf) => {
    let d = "", pen = false;
    for (let i = r0; i <= r1; i++) {
      if (series[i] == null) { pen = false; continue; }
      d += (pen ? "L" : "M") + Xr(i).toFixed(1) + " " + Yf(series[i]).toFixed(1);
      pen = true;
    }
    return d;
  };

  let g = "";
  g += `<text x="${ML - 6}" y="${MT - 10}" text-anchor="end" font-size="9.5" fill="var(--muted)" ${mono}>INDEX</text>`;
  for (let k = 0; k <= nGrid; k++) {
    const v = k * step, y = Y(v).toFixed(1);
    g += `<line x1="${ML}" y1="${y}" x2="${w - mr}" y2="${y}" stroke="${v === 0 ? "var(--axis)" : "var(--grid)"}" stroke-width="1"/>`;
    if (v > 0) g += `<text x="${ML - 6}" y="${(+y + 3.5).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)" ${mono}>${+v.toFixed(3)}</text>`;
  }
  rAxes.forEach(ax => {
    g += `<text x="${ax.x}" y="${MT - 10}" font-size="9.5" fill="${ax.color}" ${mono}>${ax.title.toUpperCase()}</text>`;
    if (!ax.has) { g += `<text x="${ax.x}" y="${MT + 12}" font-size="10" fill="var(--muted)" ${mono}>–</text>`; return; }
    for (let k = 0; k <= nGrid; k++) {
      const y = (ax.k === "gpos" ? ax.Y(1 + k * ax.step) : ax.Y(k * ax.step));
      g += `<text x="${ax.x}" y="${(y + 3.5).toFixed(1)}" font-size="10" fill="${ax.color}" ${mono}>${ax.tick(k)}</text>`;
    }
  });
  let lastR = -1e9;
  xTicks(r0, r1, iw).forEach(([i, t, anchor]) => {
    const tw = t.length * 6.1;          /* IBM Plex Mono 10px */
    let x = Xr(i);
    if (anchor === "middle") x = Math.min(w - mr - tw / 2 + 4, Math.max(ML + tw / 2 - 4, x));
    const left = anchor === "start" ? x : x - tw / 2;
    if (left < lastR + 6) return;       /* never let two labels touch */
    lastR = left + tw;
    g += `<text x="${x.toFixed(1)}" y="${h - 6}" text-anchor="${anchor}" font-size="10" fill="var(--muted)" ${mono}>${t}</text>`;
  });

  if (visible.traffic && hasTraffic) {
    const s = disp(trafIdx), p = pathOf(s, Y);
    g += `<path d="${p} L ${Xr(r1).toFixed(1)} ${Y(0).toFixed(1)} L ${ML} ${Y(0).toFixed(1)} Z" fill="var(--traffic-fill)" stroke="none"/>`;
    g += `<path d="${p}" fill="none" stroke="var(--traffic)" stroke-width="1.8" stroke-linejoin="round"/>`;
    /* selective direct label: traffic peak within the visible range */
    let pi = r0;
    for (let i = r0; i <= r1; i++) if (traf[i] > traf[pi]) pi = i;
    const px = Xr(pi), py = Y(s[pi]);
    let lx = px, ly = py - 6, anchor = px > w - mr - 90 ? "end" : px < ML + 70 ? "start" : "middle";
    if (ly < MT - 2) {                   /* no room above: put it beside the dot */
      ly = py + 3.5;
      if (px > w - mr - 120) { anchor = "end"; lx = px - 6; } else { anchor = "start"; lx = px + 6; }
    }
    g += `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="2.6" fill="var(--traffic)"/>`;
    g += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${anchor}" font-size="10" fill="var(--ink-2)" ${mono}>peak ${fmt(traf[pi])} users</text>`;
  }
  if (k25) k25.forEach((s0, i) => {
    if (!visible["k"+i] || !s0.length) return;
    const m = KW_META[i];
    g += `<path d="${pathOf(disp(s0), Y)}" fill="none" stroke="${m.color}" stroke-width="1.1"${m.dash ? ` stroke-dasharray="${m.dash}"` : ""} stroke-linejoin="round" opacity="0.3"/>`;
  });
  if (kwS) kwS.forEach((s0, i) => {
    if (!visible["k"+i] || !s0.length) return;
    const m = KW_META[i];
    g += `<path d="${pathOf(dispN(s0), Y)}" fill="none" stroke="${m.color}" stroke-width="1.6"${m.dash ? ` stroke-dasharray="${m.dash}"` : ""} stroke-linejoin="round" opacity="0.95"/>`;
  });
  gLines.forEach(([, s, col]) => {
    const d = pathOf(s, Y);
    if (d) g += `<path d="${d}" fill="none" stroke="${col}" stroke-width="1.5" stroke-linejoin="round" opacity="0.95"/>`;
  });
  rAxes.forEach(ax => {
    if (!ax.has) return;
    /* a day with no neighbours has no line segment: draw it as a dot */
    for (let i = r0; i <= r1; i++)
      if (ax.series[i] != null && (i === r0 || ax.series[i - 1] == null) && (i === r1 || ax.series[i + 1] == null))
        g += `<circle cx="${Xr(i).toFixed(1)}" cy="${ax.Y(ax.series[i]).toFixed(1)}" r="1.8" fill="${ax.color}"/>`;
    const d = pathOf(ax.series, ax.Y);
    g += ax.k === "gpos"
      ? `<path d="${d}" fill="none" stroke="var(--gp)" stroke-width="1.6" stroke-dasharray="0.1 3.2" stroke-linecap="round" stroke-linejoin="round"/>`
      : `<path d="${d}" fill="none" stroke="var(--gc)" stroke-width="1.5" stroke-linejoin="round" opacity="0.95"/>`;
  });

  if (visible.fires) {
    const fm = fireMap(st), y0 = Y(0);
    let lastCount = -1e9;
    for (const di in fm) {
      const i = +di;
      if (i < r0 || i > r1) continue;
      const x = Xr(i), n = fm[di].length;
      const anyImpact = fm[di].some(isImpactful);
      /* diamond centered on the x-axis: half above, half below */
      if (anyImpact)
        g += `<path d="M ${x.toFixed(1)} ${(y0-4.5).toFixed(1)} L ${(x+3.5).toFixed(1)} ${y0.toFixed(1)} L ${x.toFixed(1)} ${(y0+4.5).toFixed(1)} L ${(x-3.5).toFixed(1)} ${y0.toFixed(1)} Z" fill="var(--fire-mk)" stroke="var(--ink-2)" stroke-width="0.5"/>`;
      else
        g += `<path d="M ${x.toFixed(1)} ${(y0-4).toFixed(1)} L ${(x+3.1).toFixed(1)} ${y0.toFixed(1)} L ${x.toFixed(1)} ${(y0+4).toFixed(1)} L ${(x-3.1).toFixed(1)} ${y0.toFixed(1)} Z" fill="none" stroke="var(--fire-mk)" stroke-width="1.1" opacity="0.8"/>`;
      if (n > 1 && x - lastCount >= 11) {
        g += `<text x="${x.toFixed(1)}" y="${(y0-7).toFixed(1)}" text-anchor="middle" font-size="8.5" fill="var(--muted)" ${mono}>${n}</text>`;
        lastCount = x;
      }
    }
  }
  g += `<line class="xh" x1="-10" y1="${MT}" x2="-10" y2="${MT + ih}" stroke="var(--muted)" stroke-width="1" opacity="0"/>`;
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" data-w="${w}" data-mr="${mr}" role="img" aria-label="Search interest (${viewOf(st, sel).label}) vs site traffic for ${st.name}, ${rangeText()}">${g}</svg>`;
}

/* ---------- health math shared by cards + overview (one clock: WIN days) ---------- */
const WIN = 14;
/* mean of the last `win` values ending at endI, skipping missing (null) days */
function rollN(s, endI, win) {
  let sum = 0, n = 0;
  for (let i = Math.max(0, endI - win + 1); i <= endI; i++) if (s[i] != null) { sum += s[i]; n++; }
  return n ? sum / n : null;
}
function meanSeries(kwS) {
  return DATA.dates.map((_, i) => {
    let sum = 0, n = 0;
    kwS.forEach(k => { if (k.length > i && k[i] != null) { sum += k[i]; n++; } });
    return n ? sum / n : null;
  });
}
function medianOf(arr, end) {
  const a = arr.slice(0, end + 1).filter(v => v != null).sort((x, y) => x - y);
  return a.length ? a[Math.floor(a.length / 2)] : 0;
}
/* lift = mean of the last WIN days vs the series' typical (median) day; baselines floored
   so a near-zero median can't manufacture a huge multiple */
function liftPair(S, T, end) {
  const smax = Math.max(0, ...S.filter(v => v != null));
  const baseS = Math.max(medianOf(S, end), 0.05 * smax, 0.5);
  const baseT = Math.max(medianOf(T, end), 1);
  const s = rollN(S, end, WIN), t = rollN(T, end, WIN);
  return { D: s == null ? null : s / baseS, C: t == null ? null : t / baseT, baseT };
}
/* GSC totals over `win` days ending at `end` */
function gscWin(gs, end, win = WIN) {
  if (!gs || end == null || end - win + 1 < 0) return null;
  let c = 0, i = 0, pw = 0, pi = 0, days = 0;
  for (let k = end - win + 1; k <= end; k++) {
    if (gs.i[k] == null) continue;
    days++; c += gs.c[k]; i += gs.i[k];
    if (gs.p[k] != null) { pw += gs.p[k] * gs.i[k]; pi += gs.i[k]; }
  }
  return days ? { c, i, ctr: i ? c / i : null, pos: pi ? pw / pi : null } : null;
}
const liftFmt = v => v == null ? "–" : (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + "×";
function chg(now, prev) {
  if (!prev || !now) return "";
  const r = now / prev;
  return r >= 1.05 ? `<span class="up">↑${liftFmt(r)}</span>` : r <= 0.95 ? `<span class="dn">↓${liftFmt(r)}</span>` : `<span class="lbl">flat</span>`;
}

/* ---------- cards ---------- */
function modeStatsHtml(st, sel) {
  const end = N - 2;
  let h = "";
  if (!sel) {
    const hl = healthOf(st);
    if (hl) h += `<span class="pill ${STATUS[hl.status].cls}">${STATUS[hl.status].label}</span>` + (hl.sparse
      ? `<span class="lbl">search too sparse in Google Trends to judge</span>`
      : `<span><span class="lbl">search</span> <b>${liftFmt(hl.D)}</b> <span class="lbl">→ us</span> <b>${liftFmt(hl.C)}</b> <span class="lbl">vs typical, ${WIN}d</span></span>`);
    const T = st.organic && st.organic.some(v => v > 0) ? st.organic : st.traffic;
    if (T) h += `<span class="pages"><span class="lbl">organic ${WIN}d</span> <b>${fmt(rollN(T, end, WIN) * WIN)}</b></span>`;
  } else {
    const S = sel.mode && sel.mode.kwSeries ? meanSeries(sel.mode.kwSeries) : null;
    if (S && sel.traffic) {
      const lp = liftPair(S, sel.traffic, end);
      h += sparseSearch(S) ? `<span class="lbl">metro search too sparse to judge</span>`
        : `<span><span class="lbl">search</span> <b>${liftFmt(lp.D)}</b> <span class="lbl">→ our visitors</span> <b>${liftFmt(lp.C)}</b> <span class="lbl">vs typical, ${WIN}d</span></span>`;
    } else if (!S) h += `<span class="lbl">no metro search data</span>`;
    if (sel.traffic) h += `<span><span class="lbl">metro visitors ${WIN}d</span> <b>${fmt(rollN(sel.traffic, end, WIN) * WIN)}</b></span>`;
  }
  if (!sel && st.fires && st.fires.length)
    h += `<span><b>${st.fires.length}</b> <span class="lbl">fires ·</span> <b class="fscount">${st.fires.filter(isImpactful).length}</b> <span class="lbl">impactful</span></span>`;
  if (GSC && GSC_LAST != null) {
    const gs = gscOf(st, sel);
    const now = gscWin(gs, GSC_LAST), prev = gscWin(gs, GSC_LAST - WIN);
    if (now && (!sel || now.i >= 20)) {
      const dpos = now.pos != null && prev && prev.pos != null ? prev.pos - now.pos : null;
      h += `<span title="Search Console, web, ${WIN} days to ${fdate(DATA.dates[GSC_LAST])} vs the ${WIN} before · CTR ${fpct(now.ctr)}">
        <span class="lbl">GSC ${WIN}d${sel ? ` "${esc(sel.city)}"` : ""}</span> <b>${fmt(now.i)}</b> <span class="lbl">impr</span> ${chg(now.i, prev && prev.i)}
        <span class="lbl">· ${fmt(now.c)} clicks · pos</span> <b>${fposn(now.pos)}</b>${dpos == null || Math.abs(dpos) < 0.1 ? "" : dpos > 0 ? ` <span class="up">↑${dpos.toFixed(1)}</span>` : ` <span class="dn">↓${(-dpos).toFixed(1)}</span>`}</span>`;
    }
  }
  return h;
}
function buildCards() {
  const grid = document.getElementById("grid");
  grid.innerHTML = DATA.states.map((st, si) => {
    const s = st.stats;
    const msel = st.metros && st.metros.length
      ? `<select class="msel" aria-label="Area for ${st.name}"><option value="-1">All of ${st.name}</option>` +
        st.metros.map((m, mi) => `<option value="${mi}">${m.name} metro</option>`).join("") + `</select>`
      : "";
    return `<div class="card" data-si="${si}" data-msel="-1">
      <h2>${st.name} <span class="ab">${st.abbr}</span>${s ? "" : '<span class="notraffic">no site data in export</span>'}${msel}</h2>
      <div class="stats"><span class="modestats">${modeStatsHtml(st, null)}</span></div>
      <div class="chart"></div>
      <details class="tbl"><summary>Data table</summary><div class="tblwrap"></div></details>
    </div>`;
  }).join("");

  grid.querySelectorAll(".card").forEach(card => {
    const st = DATA.states[+card.dataset.si];
    card.querySelector("details").addEventListener("toggle", function () {
      const wrap = this.querySelector(".tblwrap");
      if (!this.open || wrap.dataset.built) return;
      wrap.dataset.built = "1";
      const kwS = kwOf(st) || st.kws.map(() => []);
      const gs = GSC ? gscOf(st, null) : null;
      const gh = gs ? `<th>GSC impr</th><th>GSC clicks</th><th>GSC CTR</th><th>GSC pos</th>` : "";
      let h = `<table><thead><tr><th>Date</th><th>Users</th>${st.kws.map(k => `<th>${k} (${MODE_LABEL[mode]})</th>`).join("")}${gh}</tr></thead><tbody>`;
      for (let i = 0; i < N; i++) {
        const gd = !gs ? "" : gs.i[i] == null ? `<td>–</td><td>–</td><td>–</td><td>–</td>`
          : `<td>${gs.i[i]}</td><td>${gs.c[i]}</td><td>${gs.i[i] ? fpct(gs.c[i] / gs.i[i]) : "–"}</td><td>${fposn(gs.p[i])}</td>`;
        h += `<tr><td>${DATA.dates[i]}</td><td>${st.traffic ? st.traffic[i] : "–"}</td>${kwS.map(s => `<td>${s.length && s[i] != null ? s[i] : "–"}</td>`).join("")}${gd}</tr>`;
      }
      wrap.innerHTML = h + "</tbody></table>";
    });
    const statsEl = card.querySelector(".stats");
    if (statsEl) {
      statsEl.addEventListener("pointermove", e => {
        if (!e.target.closest(".pages")) { tip.style.display = "none"; return; }
        const det = st.pagesDetail || [];
        let rows = det.slice(0, 14).map(pd =>
          `<div class="row"><span class="n">${pd[0]}</span><span class="v">${fmt(pd[1])} users</span></div>`).join("");
        if (det.length > 14) rows += `<div class="row"><span class="n" style="color:var(--muted)">+${det.length - 14} more pages</span></div>`;
        tip.innerHTML = `<div class="d">${st.name} · pages counted${st.stats ? ` · ${fmt(st.stats.total)} users since ${fdate(DATA.dates[0])}` : ""}</div>` + rows;
        tip.style.display = "block";
        const tw = tip.offsetWidth, th = tip.offsetHeight;
        let tx = e.clientX + 14, ty = e.clientY + 12;
        if (tx + tw > innerWidth - 8) tx = e.clientX - tw - 14;
        if (ty + th > innerHeight - 8) ty = e.clientY - th - 12;
        tip.style.left = tx + "px"; tip.style.top = ty + "px";
      });
      statsEl.addEventListener("pointerleave", () => { tip.style.display = "none"; });
    }
    const ms = card.querySelector(".msel");
    if (ms) ms.addEventListener("change", () => {
      card.dataset.msel = ms.value;
      card.querySelector(".modestats").innerHTML = modeStatsHtml(st, selOf(card, st));
      renderCard(card);
    });
    attachHover(card);
  });
}

function updateModeStats() {
  document.querySelectorAll(".card[data-si]").forEach(card => {
    const st = DATA.states[+card.dataset.si];
    card.querySelector(".modestats").innerHTML = modeStatsHtml(st, selOf(card, st));
  });
}

function renderCard(card, G = chartGeom()) {
  const st = DATA.states[+card.dataset.si];
  const sel = selOf(card, st);
  card.querySelector(".chart").innerHTML = renderChart(st, sel, G);
  const fc = card.querySelector(".fscount");
  if (fc) fc.textContent = (st.fires || []).filter(isImpactful).length;
}

let renderedW = 0;
function renderAll() {
  tip.style.display = "none";
  const G = chartGeom();
  renderedW = G.w;
  document.querySelectorAll(".card[data-si]").forEach(card => renderCard(card, G));
}

function openState(key) {
  stateFilter = key;
  const sf = document.getElementById("statef");
  if (sf) sf.value = key;
  applyStateFilter();
  const card = document.querySelector(`.card[data-si]:not([hidden])`);
  card && card.scrollIntoView({ behavior: "smooth", block: "start" });
}
const esc = v => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/* ---------- overview: SEO health ---------- */
const STATUS = {
  out:   { label: "outperforming", cls: "st-out",   color: "#0ca30c" },
  track: { label: "tracking",      cls: "st-track", color: "#898781" },
  miss:  { label: "missing demand", cls: "st-miss", color: "#d03b3b" },
  low:   { label: "low signal",    cls: "st-low",   color: "#898781" },
};

/* one symmetric rule for every lift-vs-lift pair: us÷search below 0.6 = missing demand,
   above 1.25 = outperforming, otherwise tracking. It applies whether search rose or fell —
   traffic falling much faster than steady search is a loss too. */
function statusOf(x, y, low) {
  if (low || x == null || y == null || !(x > 0)) return "low";
  const r = y / x;
  return r < 0.6 ? "miss" : r > 1.25 ? "out" : "track";
}

/* Google Trends returns small values only for the most recent ~14 days of each fetch and
   reports older low-volume days as 0. A series that was mostly zero before that tail has
   no usable "typical day", so its lift can't be judged. */
const FRESH0 = N - 15;
function sparseSearch(S) {
  const v = S.slice(0, FRESH0).filter(x => x != null);
  return !v.length || v.filter(x => x > 0).length / v.length < 0.5;
}
const _health = new Map();
function healthOf(st) {
  if (_health.has(st.key)) return _health.get(st.key);
  const kwS = st.modes.state && st.modes.state.kwSeries;
  const T = st.organic && st.organic.some(v => v > 0) ? st.organic : st.traffic;
  let h = null;
  if (kwS && T) {
    const end = N - 2;
    const S = meanSeries(kwS);
    const { D, C, baseT } = liftPair(S, T, end);
    const totalT = T.reduce((a, b) => a + (b || 0), 0);
    /* rough visits/week we'd have had if our traffic had risen as much as search did */
    const missed = D != null && C != null && D > C ? (D - C) * baseT * 7 : 0;
    let g = null;
    const gw = st.gsc && st.gsc.web;
    if (GSC && gw && GSC_LAST != null && gw.i.some(v => v != null)) {
      /* GSC side on its own clock (it lags ~2 days): WIN days ending GSC_LAST, demand re-measured on that window */
      const smax = Math.max(0, ...S.filter(v => v != null));
      const baseS = Math.max(medianOf(S, end), 0.05 * smax, 0.5);
      const sw = rollN(S, Math.min(GSC_LAST, end), WIN);
      const iw = rollN(gw.i, GSC_LAST, WIN), cw = rollN(gw.c, GSC_LAST, WIN);
      const now = gscWin(gw, GSC_LAST);
      g = { I: iw == null ? null : iw / Math.max(medianOf(gw.i, GSC_LAST), 1),
            C: cw == null ? null : cw / Math.max(medianOf(gw.c, GSC_LAST), 1),
            Dg: sw == null ? null : sw / baseS, ctr: now && now.ctr, pos: now && now.pos,
            low: gw.i.reduce((a, v) => a + (v || 0), 0) < 300 };
    }
    const sparse = sparseSearch(S);
    h = { st, D, C, ratio: D > 0 && C != null ? C / D : null, status: statusOf(D, C, totalT < 300 || sparse),
          sparse, totalT, t14: Math.round((rollN(T, end, WIN) || 0) * WIN), missed: sparse ? 0 : missed, g };
  }
  _health.set(st.key, h);
  return h;
}

/* the likely reason, read off Search Console (impressions = were we shown; clicks = were we chosen) */
function whyOf(h) {
  const g = h.g;
  if (!g || g.low || g.Dg == null || g.I == null) return `<span class="lbl">no Search Console signal</span>`;
  if (g.I / g.Dg < 0.6)
    return `losing visibility <span class="lbl">· impressions ${liftFmt(g.I)} vs search ${liftFmt(g.Dg)}</span>`;
  if (g.C != null && g.I > 0 && g.C / g.I < 0.6)
    return `shown, not clicked <span class="lbl">· clicks ${liftFmt(g.C)} vs impressions ${liftFmt(g.I)}</span>`;
  if (g.C != null && h.D != null && g.C >= 0.8 * h.D)
    return `Google clicks kept pace <span class="lbl">(${liftFmt(g.C)}) · gap is outside Google search</span>`;
  return `visibility and clicks both slipped <span class="lbl">· impressions ${liftFmt(g.I)}, clicks ${liftFmt(g.C)}</span>`;
}

const QPRESETS = {
  dv: { label: "search demand → our visibility", x: "search demand (Trends)", y: "our impressions (Search Console)", xs: "Search", ys: "Impressions",
        pick: h => h.g && ({ x: h.g.Dg, y: h.g.I, low: h.g.low || h.sparse }) },
  dc: { label: "search demand → our traffic", x: "search demand (Trends)", y: "our organic traffic", xs: "Search", ys: "Our traffic",
        pick: h => ({ x: h.D, y: h.C, low: h.status === "low" }) },
  vc: { label: "our visibility → our clicks", x: "our impressions (Search Console)", y: "our clicks (Search Console)", xs: "Impressions", ys: "Clicks",
        pick: h => h.g && ({ x: h.g.I, y: h.g.C, low: h.g.low }) },
};
let qpreset = GSC ? "dv" : "dc";

function stateChip(h, val) {
  return `<button class="schip orow" data-key="${h.st.key}">${h.st.abbr}<span class="lbl"> ${val}</span></button>`;
}

function buildOverview() {
  const sec = document.getElementById("overview");
  const healths = DATA.states.map(healthOf);
  if (!healths.some(Boolean)) { sec.hidden = true; return; }
  sec.hidden = false;
  const end = N - 2;
  document.getElementById("osub").textContent =
    `last ${WIN} days (to ${fdate(DATA.dates[end])}) vs each state's typical day · our traffic = organic visits`
    + (GSC && GSC_LAST != null ? ` · Search Console to ${fdate(DATA.dates[GSC_LAST])}` : "");

  const hs = healths.filter(Boolean);
  const by = st => hs.filter(h => h.status === st);
  const miss = by("miss").sort((a, b) => b.missed - a.missed);
  const hasG = GSC && hs.some(h => h.g);

  let html = miss.length
    ? `<table class="mtab score"><colgroup><col style="width:130px"><col style="width:128px"><col style="width:130px"><col style="width:96px"><col></colgroup>
       <thead><tr><th class="l">state</th><th class="l">status</th><th>search → us</th><th style="white-space:normal">est. missed visits / wk</th>
       <th class="l">${hasG ? "likely why (Search Console)" : ""}</th></tr></thead><tbody>` +
      miss.map(h => `<tr class="orow mrow" data-key="${h.st.key}" tabindex="0">
        <td class="mn">${h.st.name}</td>
        <td class="stcell"><span class="pill ${STATUS[h.status].cls}">${STATUS[h.status].label}</span></td>
        <td>${liftFmt(h.D)} → ${liftFmt(h.C)}</td>
        <td class="bad">${fmt(h.missed)}</td>
        <td class="kw why">${hasG ? whyOf(h) : ""}</td></tr>`).join("") + `</tbody></table>`
    : `<div class="mempty">No state is missing demand over the last ${WIN} days.</div>`;

  const line = (label, list, val, cls) => list.length
    ? `<div class="sline ${cls || ""}"><span class="slabel">${label}</span>${list.map(h => stateChip(h, val(h))).join("")}</div>` : "";
  html += line("outperforming", by("out").sort((a, b) => b.ratio - a.ratio), h => `${liftFmt(h.D)}→${liftFmt(h.C)}`, "s-out");
  html += line("tracking demand", by("track"), h => `${liftFmt(h.D)}→${liftFmt(h.C)}`);
  const low = by("low");
  if (low.length)
    html += `<details class="sline squiet"><summary><span class="slabel">can't judge yet</span>
      <span class="lbl">${low.length} states — Google Trends reports too few searches here to set a typical level</span></summary>
      ${low.map(h => stateChip(h, h.sparse ? "sparse search" : "low traffic")).join("")}</details>`;
  document.getElementById("oscore").innerHTML = html;

  const qsel = document.getElementById("qpreset");
  if (!qsel.options.length) {
    qsel.innerHTML = Object.entries(QPRESETS).filter(([k]) => k === "dc" || hasG)
      .map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
    qsel.value = qpreset;
    qsel.addEventListener("change", e => { qpreset = e.target.value; renderQuad(healths); });
  }
  renderQuad(healths);

  sec.querySelectorAll("#oscore .orow").forEach(el => {
    const h = healthOf(DATA.states.find(x => x.key === el.dataset.key));
    el.addEventListener("click", () => openState(el.dataset.key));
    el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openState(el.dataset.key); } });
    el.addEventListener("pointermove", e => {
      const g = h.g;
      tip.innerHTML = `<div class="d">${h.st.name} · last ${WIN} days vs typical</div>
        <table class="tt"><tbody>
        <tr><td class="n">search demand</td><td>${liftFmt(h.D)}</td></tr>
        <tr><td class="n">our organic traffic</td><td>${liftFmt(h.C)} · ${fmt(h.t14)} visits</td></tr>
        <tr><td class="n">response ratio</td><td>${h.ratio == null ? "–" : h.ratio.toFixed(2) + "×"}</td></tr>
        ${g ? `<tr><td class="n">GSC impressions</td><td>${liftFmt(g.I)}</td></tr>
        <tr><td class="n">GSC clicks</td><td>${liftFmt(g.C)}</td></tr>
        <tr><td class="n">GSC CTR · avg position</td><td>${fpct(g.ctr)} · ${fposn(g.pos)}</td></tr>` : ""}
        </tbody></table>`;
      tip.style.display = "block";
      let tx = e.clientX + 14, ty = e.clientY + 12;
      if (tx + tip.offsetWidth > innerWidth - 8) tx = e.clientX - tip.offsetWidth - 14;
      if (ty + tip.offsetHeight > innerHeight - 8) ty = e.clientY - tip.offsetHeight - 12;
      tip.style.left = tx + "px"; tip.style.top = ty + "px";
    });
    el.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  });
}

function renderQuad(healths) {
  const P = QPRESETS[qpreset];
  const QW = 420, QH = 330, QL = 48, QR = 46, QT = 14, QB = 40;
  const mono = `font-family="IBM Plex Mono, monospace"`;
  const pts = healths.filter(Boolean).map(h => {
    const v = P.pick(h);
    if (!v || v.x == null || v.y == null) return null;
    return { h, x: v.x, y: v.y, ratio: v.x > 0 ? v.y / v.x : null, status: statusOf(v.x, v.y, v.low) };
  }).filter(p => p && p.status !== "low");
  const allLifts = pts.flatMap(p => [p.x, p.y]).filter(v => v > 0);
  /* cap the axis so one extreme state (e.g. 100×+) can't squash everyone else into a corner */
  const CAP = 24;
  const lo = Math.max(0.1, Math.min(0.4, ...allLifts) * 0.85), hi = Math.min(CAP, Math.max(3, ...allLifts) * 1.2);
  const cl = v => Math.min(Math.max(v, lo), hi);
  /* a point past the cap is scaled toward the origin along its own ray, so it keeps its
     us÷search ratio (its side of the diagonal) instead of being pinned to a corner */
  const onRay = (x, y) => { const k = Math.max(x, y) > hi ? hi / Math.max(x, y) : 1; return [x * k, y * k]; };
  const LX = v => QL + (Math.log(cl(v)) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)) * (QW - QL - QR);
  const LY = v => (QH - QB) - (Math.log(cl(v)) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)) * (QH - QB - QT);
  let g = "";
  [0.25, 0.5, 1, 2, 4, 8, 16].filter(t => t >= lo && t <= hi).forEach(t => {
    const em = t === 1;
    g += `<line x1="${LX(t)}" y1="${LY(lo)}" x2="${LX(t)}" y2="${QT}" stroke="${em ? "var(--axis)" : "var(--grid)"}"/>`;
    g += `<line x1="${QL}" y1="${LY(t)}" x2="${QW - QR}" y2="${LY(t)}" stroke="${em ? "var(--axis)" : "var(--grid)"}"/>`;
    g += `<text x="${LX(t)}" y="${QH - QB + 14}" text-anchor="middle" font-size="9.5" fill="var(--muted)" ${mono}>${t}×</text>`;
    g += `<text x="${QL - 6}" y="${LY(t) + 3}" text-anchor="end" font-size="9.5" fill="var(--muted)" ${mono}>${t}×</text>`;
  });
  g += `<line x1="${LX(lo)}" y1="${LY(lo)}" x2="${LX(hi)}" y2="${LY(hi)}" stroke="var(--muted)" stroke-dasharray="5 4" opacity="0.7"/>`;
  g += `<text x="${QW - QR}" y="${QH - QB - 8}" text-anchor="end" font-size="10" fill="#d03b3b" ${mono}>↓ falling behind</text>`;
  g += `<text x="${QL + 6}" y="${QT + 10}" font-size="10" fill="#0ca30c" ${mono}>↑ outperforming</text>`;
  g += `<text x="${(QL + QW - QR) / 2}" y="${QH - 6}" text-anchor="middle" font-size="10.5" fill="var(--muted)" ${mono}>${P.x} · × typical</text>`;
  g += `<text x="12" y="${(QT + QH - QB) / 2}" text-anchor="middle" font-size="10.5" fill="var(--muted)" ${mono} transform="rotate(-90 12 ${(QT + QH - QB) / 2})">${P.y} · × typical</text>`;

  /* red dots always get a label; the rest are placed greedily so labels never overlap */
  const placed = [];
  [...pts].sort((a, b) => ({ miss: 0, out: 1, track: 2 })[a.status] - ({ miss: 0, out: 1, track: 2 })[b.status] || b.x - a.x)
    .forEach(pt => {
      const h = pt.h;
      const [rx, ry] = onRay(pt.x, pt.y);
      const cx = LX(rx), cy = LY(ry);
      const off = pt.x > hi || pt.y > hi;
      const text = off ? `${h.st.abbr} ${liftFmt(pt.x)}→${liftFmt(pt.y)}` : h.st.abbr;
      const w = text.length * 6.2 + 4;
      let bx = cx + 7;
      if (bx + w > QW - 2) bx = cx - 7 - w;
      const by = cy - 9;
      let lbl = "";
      if (pt.status === "miss" || !placed.some(p => bx < p.bx + p.w && bx + w > p.bx && by < p.by + 11 && by + 11 > p.by)) {
        placed.push({ bx, by, w });
        lbl = `<text x="${bx.toFixed(1)}" y="${(cy + 3.5).toFixed(1)}" font-size="9.5" fill="${pt.status === "miss" ? "#d03b3b" : "var(--ink-2)"}" ${mono}>${text}</text>`;
      }
      g += `<g class="dot orow" data-key="${h.st.key}" data-pi="${pts.indexOf(pt)}">
        <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5" fill="${STATUS[pt.status].color}" fill-opacity="0.85" stroke="var(--surface)" stroke-width="1"/>${lbl}</g>`;
    });
  const gEnd = GSC_LAST != null ? fdate(DATA.dates[GSC_LAST]) : "–";
  document.getElementById("oquad").innerHTML =
    `<svg viewBox="0 0 ${QW} ${QH}" role="img" aria-label="${P.label}, by state, last ${WIN} days">${g}</svg>
    <div class="qnote">${{
      dv: `<b>Did Google show us more as searching rose?</b> x = search demand, y = how often Google showed our pages
        (Search Console impressions), each as a multiple of its typical day over the ${WIN} days to ${gEnd}. Below the
        diagonal = searching grew but our visibility didn't keep up — a ranking or indexing gap.`,
      dc: `<b>Did our traffic rise with search demand?</b> x = search demand, y = our organic traffic, each as a multiple
        of its typical day over the last ${WIN} days. Below the diagonal = searching grew more than our traffic did.`,
      vc: `<b>When Google showed us, did people click?</b> x = impressions, y = clicks (Search Console, ${WIN} days to
        ${gEnd}). Below the diagonal = we were seen more but chosen proportionally less — a title, snippet or position problem.`,
    }[qpreset]} The 1× lines mark an ordinary stretch; colors come from this chart's own ratio. A state past ${CAP}×
    is drawn scaled down along its own line from the origin (so it stays on the correct side of the diagonal) and
    labelled with both values. States whose search is too sparse to judge are left off. Hover a dot for exact values;
    click to open the state.</div>`;
  const gEndTip = GSC_LAST != null && qpreset !== "dc" ? `, to ${fdate(DATA.dates[GSC_LAST])}` : "";
  document.querySelectorAll("#oquad .dot").forEach(d => {
    d.addEventListener("pointermove", e => {
      const pt = pts[+d.dataset.pi];
      tip.innerHTML = `<div class="d">${esc(pt.h.st.name)} <span class="pill ${STATUS[pt.status].cls}">${STATUS[pt.status].label}</span></div>
        <table class="tt"><tbody>
          <tr><td class="n">${P.xs}</td><td>${liftFmt(pt.x)}</td></tr>
          <tr><td class="n">${P.ys}</td><td>${liftFmt(pt.y)}</td></tr>
        </tbody></table>
        <div class="tnote">vs a typical day · last ${WIN} days${gEndTip}</div>`;
      tip.style.display = "block";
      let tx = e.clientX + 14, ty = e.clientY + 12;
      if (tx + tip.offsetWidth > innerWidth - 8) tx = e.clientX - tip.offsetWidth - 14;
      tip.style.left = tx + "px"; tip.style.top = ty + "px";
    });
    d.addEventListener("pointerleave", () => { tip.style.display = "none"; });
    d.addEventListener("click", () => openState(d.dataset.key));
  });
}

/* ---------- state filter + metro map ---------- */
const mapEl = document.createElement("div");
mapEl.className = "card mapcard";
mapEl.hidden = true;

function applyStateFilter() {
  document.querySelectorAll(".card[data-si]").forEach(card => {
    const st = DATA.states[+card.dataset.si];
    card.hidden = stateFilter !== "-1" && st.key !== stateFilter;
  });
  if (stateFilter === "-1") { mapEl.hidden = true; return; }
  const st = DATA.states.find(s => s.key === stateFilter);
  const card = document.querySelector(`.card[data-si="${DATA.states.indexOf(st)}"]`);
  const map = DATA.maps[st.key];
  if (!card || !map) { mapEl.hidden = true; return; }
  card.after(mapEl);
  renderMap(st, map);
  mapEl.hidden = false;
}

function topTermToday(m) {
  if (!m.mode || !m.mode.kwSeries) return null;
  const i = N - 2;
  let best = null;
  m.mode.kwSeries.forEach((s, k) => {
    if (!s.length || s.length <= i || s[i] == null) return;
    if (!best || s[i] > best.v) best = { k, v: s[i] };
  });
  return best && best.v > 0 ? best : null;
}

function tplTerms(st, tpl) {
  /* full keyword strings of a template family, for the expanded legend */
  const parts = [];
  KW_META.forEach((m, k) => {
    if (m.tpl !== tpl) return;
    parts.push(m.varr === "city" ? "fire near {city}" : (st.kws[k] || ""));
  });
  return parts.filter(Boolean).join(" · ");
}

function renderMap(st, map) {
  const lastFull = N - 2;
  let paths = "";
  for (const mk in map.metros) {
    const mi = st.metros.findIndex(m => m.key === mk);
    const m = st.metros[mi];
    const top = m ? topTermToday(m) : null;
    const fill = top ? KW_META[top.k].color : "var(--chip-bg)";
    const op = top ? "0.65" : "1";
    paths += `<path class="dma" d="${map.metros[mk]}" fill="${fill}" fill-opacity="${op}" data-mi="${mi}"/>`;
  }
  /* active fires overlaid as diamonds at their coordinates */
  const pj = map.proj;
  const activeFires = (st.fires || []).filter(f =>
    f.act && f.lat !== undefined &&
    f.lon >= pj.minx && (pj.maxy - f.lat) >= 0);
  let firePaths = "";
  activeFires.forEach((f, fi) => {
    const x = (f.lon - pj.minx) * pj.kx, y = (pj.maxy - f.lat) * pj.ky;
    if (x < -5 || x > map.w + 5 || y < -5 || y > map.h + 5) return;
    const imp = isImpactful(f);
    const s = imp ? 5 : 4.2;
    const style = imp
      ? `fill="var(--fire-mk)" stroke="var(--ink-2)" stroke-width="0.6"`
      : `fill="none" stroke="var(--fire-mk)" stroke-width="1.3"`;
    /* transparent halo makes the whole marker (and a bit around it) hoverable,
       so hollow diamonds hit-test like filled ones */
    firePaths += `<g class="fmk" data-fi="${fi}"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7" fill="transparent" stroke="none"/>
      <path d="M ${x.toFixed(1)} ${(y-s).toFixed(1)} L ${(x+s).toFixed(1)} ${y.toFixed(1)} L ${x.toFixed(1)} ${(y+s).toFixed(1)} L ${(x-s).toFixed(1)} ${y.toFixed(1)} Z" ${style}/></g>`;
  });

  const tplSeen = {};
  let legend = "";
  st.metros.forEach(m => {
    const top = topTermToday(m);
    if (top && !tplSeen[KW_META[top.k].tpl]) {
      tplSeen[KW_META[top.k].tpl] = true;
      legend += `<div class="li"><span class="swb" style="background:${KW_META[top.k].color};opacity:.65"></span>top term: ${tplTerms(st, KW_META[top.k].tpl)}</div>`;
    }
  });
  if (st.metros.some(m => !topTermToday(m)))
    legend += `<div class="li"><span class="swb" style="background:var(--chip-bg);border:1px solid var(--border)"></span>no term registering today</div>`;
  if (map.gap)
    legend += `<div class="li"><span class="swb" style="background:var(--grid)"></span>not in any of this state's listed markets</div>`;
  if (activeFires.length)
    legend += `<div class="li">${legendSwatch("fires")}active fire (solid = impactful)</div>
      <div class="li">${legendSwatch("fires_h")}active fire, not impactful</div>`;
  mapEl.innerHTML = `<div class="mtitle">${st.name} by metro area</div>
    <div class="msub">shaded by each metro's strongest search term on ${fdate(DATA.dates[lastFull])} (latest full day) · diamonds = currently active fires · hover for stats · click a metro to open its chart</div>
    <div class="mapbox"><svg viewBox="0 0 ${map.w} ${map.h}" role="img" aria-label="${st.name} metros by top search term"><path class="under" d="${map.outline}"/>${paths}<path class="outline" d="${map.outline}"/>${firePaths}</svg>
    <div class="maplegend">${legend}</div></div>`;

  mapEl.querySelectorAll("g.fmk").forEach(p => {
    const f = activeFires[+p.dataset.fi];
    p.addEventListener("pointermove", e => {
      const pop = f.p ? `${fmt(f.p[impact.ring])} ppl ≤${impact.ring}mi` : "pop n/a";
      tip.innerHTML = `<div class="d">${legendSwatch(isImpactful(f) ? "fires" : "fires_h")} ${f.t} fire · active</div>
        <div class="row"><span class="n">started ${fdate(f.d)}</span><span class="v">${f.a ? fmt(f.a) + " ac" : ""} · ${pop}</span></div>`;
      tip.style.display = "block";
      let tx = e.clientX + 14, ty = e.clientY + 12;
      if (tx + tip.offsetWidth > innerWidth - 8) tx = e.clientX - tip.offsetWidth - 14;
      if (ty + tip.offsetHeight > innerHeight - 8) ty = e.clientY - tip.offsetHeight - 12;
      tip.style.left = tx + "px"; tip.style.top = ty + "px";
    });
    p.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  });

  mapEl.querySelectorAll("path.dma").forEach(p => {
    const mi = +p.dataset.mi;
    const m = st.metros[mi];
    if (!m) return;
    p.addEventListener("pointermove", e => {
      const i = lastFull;
      const d7 = s => (s.length > i && i - 7 >= 0 && s[i] != null && s[i - 7] != null) ? s[i] - s[i - 7] : null;
      const cell = d => {
        if (d == null) return `<td class="zero">–</td>`;
        const v = Math.round(d * 10) / 10;
        return `<td class="${v > 0 ? "pos" : v === 0 ? "zero" : ""}">${v > 0 ? "+" : ""}${v}</td>`;
      };
      const vis7 = Math.round((rollN(m.traffic, i, 7) || 0) * 7);
      let body = `<tr><td class="n"><span class="sw">${legendSwatch("traffic")}</span>our visitors, last 7 days</td><td>${fmt(vis7)}</td><td></td></tr>`;
      const kwS = m.mode && m.mode.kwSeries;
      if (!kwS) body += `<tr><td class="n" colspan="3" style="color:var(--muted)">no search data for this metro</td></tr>`;
      else {
        const live = kwS.map((s, k) => ({ s, k })).filter(x => x.s.length > i && x.s[i] > 0).sort((a, b) => b.s[i] - a.s[i]);
        if (!live.length)
          body += `<tr><td class="n" colspan="3" style="color:var(--muted)">${kwS.every(s => s[i] == null) ? "search data missing for this day" : "no search term registering"}</td></tr>`;
        live.forEach(x => {
          body += `<tr><td class="n"><span class="sw">${legendSwatch(KW_META[x.k])}</span>${(m.kws || st.kws)[x.k]}</td><td>${Math.round(x.s[i] * 10) / 10}</td>${cell(d7(x.s))}</tr>`;
        });
      }
      const g7 = GSC ? gscWin(m.gsc && m.gsc[gscType], GSC_LAST, 7) : null;
      if (g7 && g7.i > 0)
        body += `<tr><td class="n" colspan="3" style="padding-top:6px"><span class="sw">${legendSwatch({ color: "var(--gi)" })}</span>GSC "${esc(m.city)}" queries, 7 days: <b>${fmt(g7.i)}</b> impr · <b>${fmt(g7.c)}</b> clicks</td></tr>`;
      tip.innerHTML = `<div class="d">${m.name} metro</div>
        <table class="tt"><thead><tr><th>series</th><th>${fdate(DATA.dates[i])}</th><th>Δ 7d</th></tr></thead>
        <tbody>${body}</tbody></table>`;
      tip.style.display = "block";
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      let tx = e.clientX + 14, ty = e.clientY + 12;
      if (tx + tw > innerWidth - 8) tx = e.clientX - tw - 14;
      if (ty + th > innerHeight - 8) ty = e.clientY - th - 12;
      tip.style.left = tx + "px"; tip.style.top = ty + "px";
    });
    p.addEventListener("pointerleave", () => { tip.style.display = "none"; });
    p.addEventListener("click", () => {
      const card = document.querySelector(`.card[data-si="${DATA.states.indexOf(st)}"]`);
      const ms = card && card.querySelector(".msel");
      if (ms) { ms.value = String(mi); ms.dispatchEvent(new Event("change")); }
    });
  });
}

/* ---------- metro movers ---------- */
const KW_TPL_LABEL = KW_META.map(m =>
  m.varr === "me" ? "fire near me" :
  m.varr === "city" ? "fire near {city}" :
  `${m.tpl} {${m.varr === "name" ? "state" : "abbr"}}`);

function allMetros() {
  const out = [];
  DATA.states.forEach((st, si) => (st.metros || []).forEach((m, mi) => {
    if (m.mode && m.mode.kwSeries) out.push({ st, si, m, mi });
  }));
  return out;
}

/* surging = this week's search at least 1.5× last week's, both weeks inside the most recent
   ~14 days that Google Trends reports consistently; the term must average 5+ this week */
const SURGE_WIN = 7, SURGE_FLOOR = 5, SURGE_MIN = 1.5;
function buildMovers() {
  const metros = allMetros();
  const sec = document.getElementById("movers");
  if (!metros.length) { sec.hidden = true; return; }
  sec.hidden = false;
  const end = N - 2, prevEnd = end - SURGE_WIN;
  const kwFilter = +document.getElementById("mkw").value;
  document.getElementById("mnote").textContent =
    `${fdate(DATA.dates[end - SURGE_WIN + 1])} – ${fdate(DATA.dates[end])} vs the week before`;
  const cands = [];
  metros.forEach(e => {
    let best = null;
    e.m.mode.kwSeries.forEach((s, k) => {
      if ((kwFilter >= 0 && k !== kwFilter) || !s.length) return;
      const now = rollN(s, end, SURGE_WIN), prev = rollN(s, prevEnd, SURGE_WIN);
      if (now == null || prev == null || now < SURGE_FLOOR) return;
      const x = now / Math.max(prev, 1);
      if (!best || x > best.x) best = { ...e, k, x, now, prev };
    });
    if (best && best.x >= SURGE_MIN) cands.push(best);
  });
  /* a market listed under several states (e.g. Reno under CA and NV) appears once, at its best */
  const seen = new Map();
  cands.sort((a, b) => b.x - a.x).forEach(r => { if (!seen.has(r.m.name)) seen.set(r.m.name, r); });
  const rows = [...seen.values()].slice(0, 8);
  rows.forEach(r => {
    const T = r.m.traffic || [];
    r.tNow = rollN(T, end, SURGE_WIN) || 0;
    r.tPrev = rollN(T, prevEnd, SURGE_WIN) || 0;
    r.captured = r.tNow >= 1 && r.tNow >= 1.5 * Math.max(r.tPrev, 0.5);
  });
  const showTerm = kwFilter < 0;
  const v = x => x >= 10 ? Math.round(x) : x.toFixed(1);
  document.getElementById("msurge").innerHTML = rows.length
    ? `<table class="mtab surge"><colgroup><col>${showTerm ? '<col style="width:24%">' : ""}<col style="width:88px"><col style="width:120px"><col style="width:120px"></colgroup>
       <thead><tr><th class="l">metro</th>${showTerm ? '<th class="l">surging term</th>' : ""}<th>search vs last week</th>
       <th>our visitors / day<br>last → this week</th><th class="l">status</th></tr></thead><tbody>` +
      rows.map(r => `<tr class="mrow" data-si="${r.si}" data-mi="${r.mi}" tabindex="0"
          data-tip="${esc(r.m.name)} · ${esc((r.m.kws || r.st.kws)[r.k])}: ${v(r.prev)} → ${v(r.now)} average this week (metro's own 0–100 index)">
        <td class="mn">${r.m.name}<span class="lbl"> · ${r.st.abbr}</span></td>
        ${showTerm ? `<td class="kw">${(r.m.kws || r.st.kws)[r.k]}</td>` : ""}
        <td class="up">×${r.x.toFixed(1)}</td>
        <td>${v(r.tPrev)} → ${v(r.tNow)}</td>
        <td class="stcell"><span class="pill ${r.captured ? "st-out" : "st-miss"}">${r.captured ? "capturing" : "not capturing"}</span></td></tr>`).join("") +
      `</tbody></table>`
    : `<div class="mempty">No metro's search jumped 1.5× or more this week with meaningful volume.</div>`;

  sec.querySelectorAll(".mrow").forEach(row => {
    const go = () => {
      const st = DATA.states[+row.dataset.si];
      if (stateFilter !== "-1" && st && stateFilter !== st.key) {
        stateFilter = st.key;
        document.getElementById("statef").value = st.key;
        applyStateFilter();
      }
      const card = document.querySelector(`.card[data-si="${row.dataset.si}"]`);
      if (!card) return;
      const ms = card.querySelector(".msel");
      if (ms) { ms.value = row.dataset.mi; ms.dispatchEvent(new Event("change")); }
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    row.addEventListener("click", go);
    row.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    row.addEventListener("pointermove", e => {
      tip.innerHTML = `<div class="d" style="margin:0">${row.dataset.tip}</div>`;
      tip.style.display = "block";
      let tx = e.clientX + 14, ty = e.clientY + 12;
      if (tx + tip.offsetWidth > innerWidth - 8) tx = e.clientX - tip.offsetWidth - 14;
      tip.style.left = tx + "px"; tip.style.top = ty + "px";
    });
    row.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  });
}

function initMovers() {
  const sel = document.getElementById("mkw");
  sel.innerHTML = `<option value="-1">any term</option>` +
    KW_TPL_LABEL.map((l, k) => `<option value="${k}">${l}</option>`).join("");
  sel.addEventListener("change", buildMovers);
  buildMovers();
}

/* ---------- top search opportunities (Search Console) ---------- */
function buildTopQueries() {
  const sec = document.getElementById("tq");
  const tq = GSC && GSC.topQueries && GSC.topQueries.web;
  if (!tq || !tq.groups) { sec.hidden = true; return; }
  sec.hidden = false;
  document.getElementById("tqnote").textContent =
    `web search · ${fdate(GSC.topWindow[0])} – ${fdate(GSC.topWindow[1])} vs the ${WIN} days before`;
  const known = new Set(DATA.states.map(x => x.key));
  const TAG = { "page 2+": "st-miss", "weak snippet": "st-low", "new demand": "st-track", "old page": "st-low" };
  const trend = g => {
    const r = g.i0 ? g.i / g.i0 : Infinity;
    if (r >= 20) return `<span class="pill st-track">new</span>`;
    if (r >= 2) return `<span class="up">×${r.toFixed(r >= 10 ? 0 : 1)}</span>`;
    return `<span class="${r >= 1 ? "up" : "dn"}">${r >= 1 ? "+" : ""}${Math.round((r - 1) * 100)}%</span>`;
  };
  document.getElementById("tqlist").innerHTML = tq.groups.length
    ? `<table class="mtab tqtab"><colgroup><col style="width:24%"><col><col style="width:78px"><col style="width:112px"><col style="width:86px"><col style="width:190px"></colgroup>
       <thead><tr><th class="l">page</th><th class="l">biggest query opportunity</th><th class="l">queries</th><th style="white-space:normal">page impressions ${WIN}d</th><th style="white-space:normal">extra clicks / week</th><th class="l">reason</th></tr></thead>` +
      tq.groups.map((g, gi) => `<tbody class="tqg">
        <tr class="${known.has(g.state) ? "mrow tqrow" : "tqrow-x"}" data-key="${g.state || ""}" data-gi="${gi}" tabindex="0">
          <td class="mn">${esc(g.label)}${g.state_label ? `<span class="lbl"> · ${g.state_label}</span>` : ""}</td>
          <td class="kw" title="${esc(g.queries[0].q)} — ${fmt(g.queries[0].i)} impressions at position ${fposn(g.queries[0].pos)}, ${fmt(g.queries[0].c)} clicks">${esc(g.queries[0].q)}</td>
          <td class="l">${g.n > 1 ? `<button class="more" data-gi="${gi}" aria-expanded="false">${fmt(g.n)} ▸</button>` : "1"}</td>
          <td>${fmt(g.i)} ${trend(g)}</td>
          <td class="up">${fmt(g.pot)}</td>
          <td class="stcell">${g.tags.map(t => `<span class="pill ${TAG[t] || "st-low"}">${t}</span>`).join(" ")}</td></tr>
        ${g.queries.map(q => `<tr class="sub" data-gi="${gi}" hidden><td></td><td class="kw" title="${esc(q.q)}">${esc(q.q)}</td>
          <td></td><td>${fmt(q.i)} <span class="lbl">impr · ${fmt(q.c)} clk</span></td><td>${q.pot >= 1 ? fmt(q.pot) : "–"}</td><td class="lbl">pos ${fposn(q.pos)}</td></tr>`).join("")}
        ${g.n > g.queries.length ? `<tr class="sub" data-gi="${gi}" hidden><td></td><td class="lbl" colspan="5">+${fmt(g.n - g.queries.length)} smaller queries</td></tr>` : ""}
        </tbody>`).join("") + `</table>`
    : `<div class="mempty">No page has a meaningful click opportunity right now.</div>`;

  const tbl = document.getElementById("tqlist");
  tbl.querySelectorAll("button.more").forEach(btn => btn.addEventListener("click", e => {
    e.stopPropagation();
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = `${fmt(tq.groups[+btn.dataset.gi].n)} ${open ? "▾" : "▸"}`;
    tbl.querySelectorAll(`tr.sub[data-gi="${btn.dataset.gi}"]`).forEach(r => { r.hidden = !open; });
  }));
  tbl.querySelectorAll("tr.tqrow, tr.tqrow-x").forEach(row => {
    const g = tq.groups[+row.dataset.gi];
    if (row.classList.contains("tqrow")) {
      row.addEventListener("click", e => { if (!e.target.closest("button")) openState(row.dataset.key); });
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" && !e.target.closest("button")) { e.preventDefault(); openState(row.dataset.key); }
      });
    }
    row.addEventListener("pointermove", e => {
      const prev = v => g.c0 == null ? "–" : v;
      tip.innerHTML = `<div class="d">${esc(g.label)} <span class="lbl">/${esc(g.page)}</span></div>
        <table class="tt"><thead><tr><th></th><th>last ${WIN}d</th><th>prior ${WIN}d</th></tr></thead><tbody>
        <tr><td class="n">impressions</td><td>${fmt(g.i)}</td><td>${fmt(g.i0)}</td></tr>
        <tr><td class="n">clicks</td><td>${fmt(g.c)}</td><td>${prev(fmt(g.c0))}</td></tr>
        <tr><td class="n">CTR</td><td>${fpct(g.i ? g.c / g.i : null)}</td><td>${prev(fpct(g.i0 ? g.c0 / g.i0 : null))}</td></tr>
        <tr><td class="n">avg position</td><td>${fposn(g.pos)}</td><td>${prev(fposn(g.pos0))}</td></tr>
        </tbody></table>
        <div class="tnote">${fmt(g.n)} search ${g.n === 1 ? "query lands" : "queries land"} on this page${known.has(g.state) ? "" : " · state not on this dashboard"}</div>`;
      tip.style.display = "block";
      let tx = e.clientX + 14, ty = e.clientY + 12;
      if (tx + tip.offsetWidth > innerWidth - 8) tx = e.clientX - tip.offsetWidth - 14;
      if (ty + tip.offsetHeight > innerHeight - 8) ty = e.clientY - tip.offsetHeight - 12;
      tip.style.left = tx + "px"; tip.style.top = ty + "px";
    });
    row.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  });
}

/* ---------- hover ---------- */
const tip = document.getElementById("tip");
function attachHover(card) {
  const st = DATA.states[+card.dataset.si];
  card.querySelectorAll(".chart").forEach(chart => chart.addEventListener("pointermove", e => {
    const { r0, r1 } = range;
    const svg = chart.querySelector("svg");
    if (!svg) return;
    const w = +svg.getAttribute("data-w"), mr = +svg.getAttribute("data-mr"), iw = w - ML - mr;
    const r = svg.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width * w;
    if (fx < ML - 6 || fx > w - mr + 6) { hideTip(chart); return; }
    const i = Math.max(r0, Math.min(r1, Math.round(r0 + (fx - ML) / iw * (r1 - r0))));
    const xi = ML + ((i - r0) / (r1 - r0)) * iw;
    chart.querySelectorAll(".xh").forEach(xh => {
      xh.setAttribute("x1", xi); xh.setAttribute("x2", xi); xh.setAttribute("opacity", "0.55");
    });
    const sel = selOf(card, st);
    const { traf, kwS, kws } = viewOf(st, sel);
    const row = (sw, name, v) => `<div class="row"><span class="n">${sw} ${name}</span><span class="v">${v}</span></div>`;
    const muted = t => `<div class="row"><span class="n" style="color:var(--muted)">${t}</span></div>`;
    let rows = "";
    if (visible.traffic && traf) rows += row(legendSwatch("traffic"), "our traffic", `${traf[i]} visits`);
    if (kwS) {
      const on = kwS.map((s, k) => k).filter(k => visible["k" + k] && kwS[k].length);
      const missing = on.every(k => kwS[k][i] == null);
      const pos = on.filter(k => kwS[k][i] > 0).sort((a, b) => kwS[b][i] - kwS[a][i]);
      const zero = on.filter(k => kwS[k][i] === 0);
      pos.forEach(k => { rows += row(legendSwatch(KW_META[k]), kws[k], kwS[k][i]); });
      if (missing && on.length) rows += muted("search data missing for this day");
      else if (zero.length) rows += muted(`0: ${zero.map(k => kws[k]).join(", ")}`);
    }
    if (visible.fires) {
      const todays = [...(fireMap(st)[i] || [])].sort((a, b) => isImpactful(b) - isImpactful(a));
      todays.slice(0, 3).forEach(f => {
        const pop = f.p ? `${fmt(f.p[impact.ring])} ppl ≤${impact.ring}mi` : "pop n/a";
        rows += row(legendSwatch(isImpactful(f) ? "fires" : "fires_h"), `${f.t} started`, `${f.a ? fmt(f.a) + " ac" : ""} · ${pop}`);
      });
      if (todays.length > 3) {
        const rest = todays.slice(3);
        rows += muted(`+${rest.length} more fires (${rest.filter(isImpactful).length} impactful)`);
      }
    }
    const gs = GSC ? gscOf(st, sel) : null;
    if (gs && (visible.gi || visible.gpos || visible.gctr)) {
      const who = sel ? ` "${esc(sel.city)}"` : "";
      if (gs.i[i] == null) rows += muted("Search Console: not in yet (~2-day lag)");
      else {
        if (visible.gi) rows += row(legendSwatch({ color: "var(--gi)" }), `GSC${who} impressions`, `${fmt(gs.i[i])} · ${fmt(gs.c[i])} clicks`);
        if (visible.gpos) rows += row(legendSwatch({ color: "var(--gp)", dash: "0.1 3.6", cap: true }), `GSC${who} avg position`, fposn(gs.p[i]));
        if (visible.gctr) rows += row(legendSwatch({ color: "var(--gc)" }), `GSC${who} CTR`, gs.i[i] ? fpct(gs.c[i] / gs.i[i]) : "–");
      }
    }
    tip.innerHTML = `<div class="d">${st.name}${sel ? ` · ${sel.name} metro` : ""} · ${fdateY(DATA.dates[i])}</div>` + rows;
    tip.style.display = "block";
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let tx = e.clientX + 14, ty = e.clientY + 12;
    if (tx + tw > innerWidth - 8) tx = e.clientX - tw - 14;
    if (ty + th > innerHeight - 8) ty = e.clientY - th - 12;
    tip.style.left = tx + "px"; tip.style.top = ty + "px";
  }));
  card.querySelectorAll(".chart").forEach(chart =>
    chart.addEventListener("pointerleave", () => hideTip(chart)));
}
function hideTip(el) {
  tip.style.display = "none";
  if (el) el.querySelectorAll(".xh").forEach(xh => xh.setAttribute("opacity", "0"));
}

/* ---------- boot ---------- */
function updateMeta() {
  document.getElementById("meta").textContent =
    `${DATA.timeframe.replace(" ", " → ")} · ${MODE_GEO[mode]} · ${DATA.states.length} states · ` +
    (DATA.fetchedAt ? `traffic via PostHog as of ${DATA.fetchedAt} · ` : "") + `built __GENERATED__`;
}
updateMeta();
buildControls();
buildCards();
buildOverview();
initMovers();
buildTopQueries();
renderAll();
let resizeRaf = 0;
addEventListener("resize", () => {
  cancelAnimationFrame(resizeRaf);
  resizeRaf = requestAnimationFrame(() => { if (chartGeom().w !== renderedW) renderAll(); });
});
</script>
"""

html = HTML.replace("__DATA__", json.dumps(payload, separators=(",", ":"))).replace("__GENERATED__", generated)
with open(OUT, "w") as f:
    f.write(html)
n_traffic = sum(1 for s in states_payload if s["stats"])
print(f"wrote {OUT} ({len(html)//1024} KB): {len(states_payload)} states "
      f"({n_traffic} with traffic, {len(states_payload)-n_traffic} trends-only)")
