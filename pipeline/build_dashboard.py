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
            "kws": m_entry["keywords"] if m_entry else None,
            "mode": m_mode,
        })
    metros_payload.sort(key=lambda m: m["name"])

    states_payload.append({
        "key": key,
        "name": key.replace("_", " ").replace("-", " ").title(),
        "abbr": ref["abbr"],
        "traffic": [round(v) for v in total_series] if total_series else None,
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

payload = {"dates": dates, "timeframe": tr_state["meta"]["timeframe"],
           "has25": bool(tr25_state or tr25_natl), "hasNatl": bool(tr_natl),
           "fetchedAt": fetched_at, "states": states_payload, "maps": maps}
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
    --traffic: #a3a19a;
    --traffic-fill: rgba(137,135,129,.22);
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
  .smooth { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-2); font-size: 12.5px; cursor: pointer; }
  .smooth input { accent-color: var(--fm); }
  .axis-note { width: 100%; color: var(--muted); font-size: 11.5px; padding-top: 2px; }

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
  .mrow {
    display: flex; align-items: baseline; gap: 8px; width: 100%;
    font: inherit; font-size: 12.5px; color: var(--ink-2); text-align: left;
    background: none; border: 0; border-top: 1px solid var(--grid);
    padding: 5px 2px; cursor: pointer;
  }
  .mrow:hover { background: var(--chip-bg); }
  .mrow:focus-visible { outline: 2px solid var(--fm); outline-offset: -2px; }
  .mrow .rk { color: var(--muted); font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 11px; width: 14px; }
  .mrow .mn { color: var(--ink); font-weight: 600; }
  .mrow .ab { color: var(--muted); font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 10.5px; }
  .mrow .kw { color: var(--ink-2); }
  .mrow .val { margin-left: auto; font-family: "IBM Plex Mono", ui-monospace, monospace; color: var(--ink); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .mrow .val .up { color: var(--f); font-weight: 600; }
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
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  @media (max-width: 900px) { .charts { grid-template-columns: 1fr; } }
  .chart .rlabel {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 10.5px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .05em;
    margin: 6px 0 2px;
  }

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
  Every series is indexed so timing and shape line up: <b>100&nbsp;= that area's peak in the window</b>.
  Search interest is measured in-state (queries from within the state), or per metro via the dropdown on each card.
  Hover any chart for exact values; raw user counts are in the tooltip and tables.</p>

  <div class="controls" id="controls"></div>
  <section class="movers" id="movers" hidden>
    <div class="mhead">
      <h2>Top Metros</h2>
      <select id="mkw" aria-label="Search term for movers"></select>
      <span class="mnote" id="mnote"></span>
    </div>
    <div class="mcols">
      <div class="mcol"><h3>Biggest day-over-day jump</h3><div id="mdod"></div></div>
      <div class="mcol"><h3>Closest to their 7-day high</h3><div id="m7d"></div></div>
    </div>
  </section>
  <div class="grid" id="grid"></div>

  <footer class="notes">
    <p><b>Method.</b> Site traffic is pulled from the PostHog API at build time — the header shows when. State and
    metro totals are true daily uniques (a person visiting several of a state's pages in one day counts once);
    the per-page list in the "counting" tooltip counts a person once per page visited, so pages can sum to more than
    the total. Trends data: Google Trends daily interest over the same window, measured <b>in-state</b> (queries made
    from within the state itself, geo US-XX) or per metro (see Metro view). Keywords: wildfire {state},
    fire {state}, fire {abbr}, and "fire near me" everywhere, plus "fire near {city}" (the metro's biggest city)
    in metro view only. Each area's full keyword set fits in a single Google Trends request, so all of an area's
    terms share one normalization — the best term-day in that area = 100, values never exceed 100, and terms are
    directly comparable to each other within an area. Index values are still not comparable across areas.</p>
    <p><b>Correlation methodology.</b> For each state and geography mode (and each metro), two daily series are compared
    over the window: traffic u<sub>t</sub> = unique users summed across all of that state's pages on day t
    (the state page plus every fire page), and search s<sub>t</sub> = the unweighted mean of that area's keyword
    indices on day t (each keyword 0–100; because Google normalizes the set jointly, the mean is effectively
    weighted toward the highest-volume keywords). <b>corr r</b> is the Pearson product-moment correlation between
    u<sub>t</sub> and s<sub>t</sub> across all day-pairs — raw daily values, no smoothing (the 7-day toggle
    affects display only, never r), no lag offset, no log transform. Read it as "do high-search days coincide with
    high-traffic days": both series are spike-dominated, so r mostly reflects whether the major spikes land on the
    same days. A low r despite similar shapes usually means traffic lagged search by a few days — use the zoom view
    to eyeball lead/lag. <b>Traffic peak</b> = day of max u<sub>t</sub>; <b>search peak</b> = day of the single
    highest keyword index across the set (that keyword shown in parentheses). r is descriptive, not a significance
    test — both series are non-stationary, so no p-value is meaningful here.</p>
    <p><b>Zoom view.</b> The right-hand chart shows the same indexed series restricted to July 1 – end of window,
    with its y-axis rescaled to the maximum visible in that period; index values are unchanged from the full view.</p>
    <p><b>Metro view.</b> The dropdown on a state card narrows both series to one metro area: site traffic counts only
    visitors whose GeoIP location is within 50 miles of the metro's biggest city (still viewing that state's pages), and
    search interest is fetched for the metro's own Google Trends market (Nielsen DMA, e.g. geo US-OR-820 for Portland).
    A state's dropdown lists every DMA Google files under that state — cross-border markets (Denver appears under
    Nebraska and Wyoming too) use that state's keywords, capturing spillover audiences. Metro search indices are
    normalized within the metro, so compare shapes, not levels, against the state view.</p>
    <p><b>Top Metros.</b> Ranks all fetched metros by recent search momentum, per term or best term per metro.
    "Biggest day-over-day jump" = the change in a term's index between the last two full days (Google's final day is
    partial and excluded). "Closest to their 7-day high" = the trailing 7-day average as a share of that metro's best
    7-day average in the window (100% = the term is at its 7-day high right now). Both metrics are computed on each
    metro's own 0–100 index, so they measure momentum relative to that metro's own history — not absolute search
    volume across metros. Click a row to jump to that metro's chart.</p>
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
const visible = { traffic: true, k0: true, k1: true, k2: true, k3: true, k4: true, fires: true };
let smooth = false;
let y25 = false;
let mode = "state";
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

/* ---------- controls / legend ---------- */
function legendSwatch(meta) {
  if (meta === "traffic")
    return '<svg width="22" height="12" aria-hidden="true"><rect x="1" y="4" width="20" height="7" rx="1.5" fill="var(--traffic-fill)"/><line x1="1" y1="4" x2="21" y2="4" stroke="var(--traffic)" stroke-width="2"/></svg>';
  if (meta === "fires")
    return '<svg width="22" height="12" aria-hidden="true"><path d="M11 1.5 L15 6 L11 10.5 L7 6 Z" fill="var(--fire-mk)" stroke="var(--ink-2)" stroke-width="0.6"/></svg>';
  if (meta === "fires_h")
    return '<svg width="22" height="12" aria-hidden="true"><path d="M11 2 L14.5 6 L11 10 L7.5 6 Z" fill="none" stroke="var(--fire-mk)" stroke-width="1.4"/></svg>';
  return `<svg width="22" height="12" aria-hidden="true"><line x1="1" y1="6" x2="21" y2="6" stroke="${meta.color}" stroke-width="2.4"${meta.dash ? ` stroke-dasharray="${meta.dash}"` : ""}/></svg>`;
}
let stateFilter = "-1";
function buildControls() {
  const c = document.getElementById("controls");
  let html = `<select class="statef" id="statef" aria-label="State filter"><option value="-1">All states</option>` +
    DATA.states.map(st => `<option value="${st.key}">${st.name}</option>`).join("") + `</select>`;
  html += DATA.hasNatl ? `<span class="seg" role="group" aria-label="Trends geography">
    <button data-m="state" class="on" aria-pressed="true">in-state</button>
    <button data-m="national" aria-pressed="false">national</button></span>` : "";
  html += `<button class="lg" data-k="traffic" aria-pressed="true">${legendSwatch("traffic")}<span class="sw">site traffic</span></button>`;
  KW_META.forEach((m, i) => {
    const lbl = m.varr === "me" ? "fire near me"
      : m.varr === "city" ? `fire near <span style="color:var(--muted)">{city} · metro view</span>`
      : `${m.tpl} <span style="color:var(--muted)">{${m.varr === "name" ? "state" : "abbr"}}</span>`;
    html += `<button class="lg" data-k="k${i}" aria-pressed="true">${legendSwatch(m)}<span class="sw">${lbl}</span></button>`;
  });
  html += `<button class="lg" data-k="fires" aria-pressed="true">${legendSwatch("fires")}<span class="sw">fire starts <span style="color:var(--muted)">&gt;100 ac</span></span></button>`;
  html += `<span class="impact" title="A fire is impactful when at least this many people (2020 Census) live within this distance of its start point, measured from the fire's approximate edge">
    ${legendSwatch("fires")} impactful ≥
    <input type="range" id="ipop" min="0" max="${POP_STEPS.length-1}" step="1" value="${POP_STEPS.indexOf(impact.pop)}" aria-label="Impactful population threshold">
    <b id="ipopv">2k</b> ppl within
    <input type="range" id="irad" min="0" max="${RING_STEPS.length-1}" step="1" value="${RING_STEPS.indexOf(impact.ring)}" aria-label="Impactful radius">
    <b id="iradv">5 mi</b></span>`;
  html += `<span class="gap"></span>`;
  if (DATA.has25) html += `<label class="smooth"><input type="checkbox" id="y25t"> 2025 trends</label>`;
  html += `<label class="smooth"><input type="checkbox" id="sm"> 7-day smooth</label>`;
  html += `<div class="axis-note">${DATA.hasNatl ? "Trends geography: <b>in-state</b> = searches from within the state, <b>national</b> = all US. " : "State charts show in-state search interest (searches made from within the state); pick a metro on a card for metro-level data. "}
    Click a legend chip to show/hide that series everywhere. Solid = full state name, dashed = two-letter abbreviation. y-axis: index, 100 = peak in window.
    Fire markers: ${legendSwatch("fires")} = impactful under the current sliders, ${legendSwatch("fires_h")} = not.</div>`;
  c.innerHTML = html;
  document.getElementById("statef").addEventListener("change", e => {
    stateFilter = e.target.value;
    applyStateFilter();
  });
  c.querySelectorAll(".seg button").forEach(btn => btn.addEventListener("click", () => {
    if (mode === btn.dataset.m) return;
    mode = btn.dataset.m;
    c.querySelectorAll(".seg button").forEach(b => {
      const on = b.dataset.m === mode;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    document.querySelectorAll(".tblwrap").forEach(w => { delete w.dataset.built; w.innerHTML = ""; });
    updateMeta();
    updateModeStats();
    renderAll();
  }));
  c.querySelectorAll(".lg").forEach(btn => btn.addEventListener("click", () => {
    const k = btn.dataset.k;
    visible[k] = !visible[k];
    btn.classList.toggle("off", !visible[k]);
    btn.setAttribute("aria-pressed", String(visible[k]));
    renderAll();
  }));
  document.getElementById("sm").addEventListener("change", e => { smooth = e.target.checked; renderAll(); });
  const y25t = document.getElementById("y25t");
  if (y25t) y25t.addEventListener("change", e => { y25 = e.target.checked; renderAll(); });
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
const W = 860, H = 248, ML = 38, MR = 10, MT = 20, MB = 22;
const IW = W - ML - MR, IH = H - MT - MB;
const N = DATA.dates.length;
const zoomStart = Math.max(0, DATA.dates.findIndex(d => d >= DATA.dates[N-1].slice(0, 4) + "-07-01"));
const DIDX = {};
DATA.dates.forEach((d, i) => DIDX[d] = i);
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
const RANGES = { full: [0, N-1], zoom: [zoomStart, N-1] };
const RANGE_LABEL = {
  full: `full window · ${fdate(DATA.dates[0])} – ${fdate(DATA.dates[N-1])}`,
  zoom: `zoom · ${fdate(DATA.dates[zoomStart])} – ${fdate(DATA.dates[N-1])}`,
};

function niceAxis(rawMax) {
  if (!(rawMax > 0)) rawMax = 100;
  const pow = Math.pow(10, Math.floor(Math.log10(rawMax / 4)));
  let step = 10 * pow;
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (rawMax / (m * pow) <= 4.5) { step = m * pow; break; }
  }
  return { step, ymax: Math.ceil(rawMax / step) * step };
}

function renderChart(st, rkey, sel) {
  const [r0, r1] = RANGES[rkey];
  const Xr = i => ML + ((i - r0) / (r1 - r0)) * IW;
  const { traf, kwS, k25 } = viewOf(st, sel);
  const hasTraffic = !!traf;
  const trafMax = hasTraffic ? Math.max(...traf, 1) : 1;
  const trafIdx = hasTraffic ? traf.map(v => v / trafMax * 100) : null;
  const disp = s => smooth ? smooth7(s) : s;

  let rawMax = 0;
  const scan = s => { for (let i = r0; i <= r1; i++) if (s[i] > rawMax) rawMax = s[i]; };
  if (visible.traffic && hasTraffic) scan(disp(trafIdx));
  if (kwS) kwS.forEach((s, i) => { if (visible["k"+i] && s.length) scan(disp(s)); });
  if (k25) k25.forEach((s, i) => { if (visible["k"+i] && s.length) scan(disp(s)); });
  if (rkey === "full") rawMax = Math.max(rawMax, 100);
  const { step, ymax } = niceAxis(rawMax);
  const Y = v => MT + IH - (v / ymax) * IH;

  function path(series) {
    let d = "";
    for (let i = r0; i <= r1; i++) d += (i > r0 ? "L" : "M") + Xr(i).toFixed(1) + " " + Y(series[i]).toFixed(1);
    return d;
  }

  let g = "";
  for (let k = 0; k * step <= ymax + 1e-9; k++) {
    const v = k * step;
    g += `<line x1="${ML}" y1="${Y(v).toFixed(1)}" x2="${W-MR}" y2="${Y(v).toFixed(1)}" stroke="${v === 0 ? "var(--axis)" : "var(--grid)"}" stroke-width="1"/>`;
    if (v > 0) g += `<text x="${ML-6}" y="${(Y(v)+3.5).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="IBM Plex Mono, monospace">${step < 1 ? v.toFixed(1) : v}</text>`;
  }
  for (let i = r0; i <= r1; i++) if (DATA.dates[i].slice(8) === "01") {
    const [y, m] = DATA.dates[i].split("-");
    g += `<text x="${Xr(i).toFixed(1)}" y="${H-6}" font-size="10" fill="var(--muted)" font-family="IBM Plex Mono, monospace">${new Date(+y, m-1, 1).toLocaleDateString(undefined, {month:"short"})}</text>`;
  }

  if (visible.traffic && hasTraffic) {
    const s = disp(trafIdx);
    g += `<path d="${path(s)} L ${(W-MR).toFixed(1)} ${Y(0).toFixed(1)} L ${ML} ${Y(0).toFixed(1)} Z" fill="var(--traffic-fill)" stroke="none"/>`;
    g += `<path d="${path(s)}" fill="none" stroke="var(--traffic)" stroke-width="1.8" stroke-linejoin="round"/>`;
    /* selective direct label: traffic peak within the visible range */
    let pi = r0;
    for (let i = r0; i <= r1; i++) if (traf[i] > traf[pi]) pi = i;
    const px = Xr(pi), anchor = px > W - 130 ? "end" : px < ML + 70 ? "start" : "middle";
    const py = Y(s[pi]);
    g += `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="2.6" fill="var(--traffic)"/>`;
    g += `<text x="${px.toFixed(1)}" y="${(Math.max(10, py-6)).toFixed(1)}" text-anchor="${anchor}" font-size="10" fill="var(--ink-2)" font-family="IBM Plex Mono, monospace">peak ${fmt(traf[pi])} users</text>`;
  }
  if (k25) k25.forEach((s0, i) => {
    if (!visible["k"+i] || !s0.length) return;
    const m = KW_META[i];
    g += `<path d="${path(disp(s0))}" fill="none" stroke="${m.color}" stroke-width="1.1"${m.dash ? ` stroke-dasharray="${m.dash}"` : ""} stroke-linejoin="round" opacity="0.3"/>`;
  });
  if (kwS) kwS.forEach((s0, i) => {
    if (!visible["k"+i] || !s0.length) return;
    const m = KW_META[i];
    g += `<path d="${path(disp(s0))}" fill="none" stroke="${m.color}" stroke-width="1.6"${m.dash ? ` stroke-dasharray="${m.dash}"` : ""} stroke-linejoin="round" opacity="0.95"/>`;
  });

  if (visible.fires) {
    const fm = fireMap(st), y0 = Y(0);
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
      if (n > 1) g += `<text x="${x.toFixed(1)}" y="${(y0-7).toFixed(1)}" text-anchor="middle" font-size="8.5" fill="var(--muted)" font-family="IBM Plex Mono, monospace">${n}</text>`;
    }
  }
  g += `<line class="xh" x1="-10" y1="${MT}" x2="-10" y2="${MT+IH}" stroke="var(--muted)" stroke-width="1" opacity="0"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Search interest (${viewOf(st, sel).label}) vs site traffic for ${st.name}, ${RANGE_LABEL[rkey]}">${g}</svg>`;
}

/* ---------- cards ---------- */
function modeStatsHtml(st, sel) {
  const m = sel ? sel.mode : st.modes[mode];
  const where = sel ? `${sel.name} metro` : MODE_LABEL[mode];
  if (!m) return `<span class="lbl">no ${where} trends data</span>`;
  let h = "";
  if (sel) {
    const mu = sel.traffic.reduce((a, b) => a + b, 0);
    h += `<span><span class="lbl">metro users</span> <b>${fmt(mu)}</b></span>`;
  }
  if (m.searchPeakDate)
    h += `<span><span class="lbl">search peak</span> <b>${fdate(m.searchPeakDate)}</b> <span class="lbl">(${m.searchPeakKw})</span></span>`;
  else
    h += `<span><span class="lbl">search peak</span> <b>–</b></span>`;
  h += `<span><span class="lbl">corr r</span> <b>${m.r === null ? "–" : m.r.toFixed(2)}</b></span>`;
  if (sel) h += `<span class="lbl">trends geo: metro DMA</span>`;
  return h;
}
function buildCards() {
  const grid = document.getElementById("grid");
  grid.innerHTML = DATA.states.map((st, si) => {
    const s = st.stats;
    const fixed = s
      ? `<span><span class="lbl">users in window</span> <b>${fmt(s.total)}</b></span>
         <span><span class="lbl">traffic peak</span> <b>${fdate(s.peakTrafficDate)}</b></span>
         <span class="pages"><span class="lbl">counting</span> <b>${st.pagesLabel}</b></span>`
      : "";
    const firestat = st.fires && st.fires.length
      ? `<span><span class="lbl">fires</span> <b>${st.fires.length}</b> <span class="lbl">· impactful</span> <b class="fscount"></b></span>`
      : "";
    const msel = st.metros && st.metros.length
      ? `<select class="msel" aria-label="Area for ${st.name}"><option value="-1">All of ${st.name}</option>` +
        st.metros.map((m, mi) => `<option value="${mi}">${m.name} metro</option>`).join("") + `</select>`
      : "";
    return `<div class="card" data-si="${si}" data-msel="-1">
      <h2>${st.name} <span class="ab">${st.abbr}</span>${s ? "" : '<span class="notraffic">no site data in export</span>'}${msel}</h2>
      <div class="stats">${fixed}${firestat}<span class="modestats">${modeStatsHtml(st, null)}</span></div>
      <div class="charts">
        <div class="chart" data-r="full"></div>
        <div class="chart" data-r="zoom"></div>
      </div>
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
      let h = `<table><thead><tr><th>Date</th><th>Users</th>${st.kws.map(k => `<th>${k} (${MODE_LABEL[mode]})</th>`).join("")}</tr></thead><tbody>`;
      for (let i = 0; i < N; i++)
        h += `<tr><td>${DATA.dates[i]}</td><td>${st.traffic ? st.traffic[i] : "–"}</td>${kwS.map(s => `<td>${s.length ? s[i] : "–"}</td>`).join("")}</tr>`;
      wrap.innerHTML = h + "</tbody></table>";
    });
    const pg = card.querySelector(".pages");
    if (pg) {
      pg.addEventListener("pointermove", e => {
        const det = st.pagesDetail || [];
        let rows = det.slice(0, 14).map(pd =>
          `<div class="row"><span class="n">${pd[0]}</span><span class="v">${fmt(pd[1])} users</span></div>`).join("");
        if (det.length > 14) rows += `<div class="row"><span class="n" style="color:var(--muted)">+${det.length - 14} more pages</span></div>`;
        tip.innerHTML = `<div class="d">${st.name} · pages counted</div>` + rows;
        tip.style.display = "block";
        const tw = tip.offsetWidth, th = tip.offsetHeight;
        let tx = e.clientX + 14, ty = e.clientY + 12;
        if (tx + tw > innerWidth - 8) tx = e.clientX - tw - 14;
        if (ty + th > innerHeight - 8) ty = e.clientY - th - 12;
        tip.style.left = tx + "px"; tip.style.top = ty + "px";
      });
      pg.addEventListener("pointerleave", () => { tip.style.display = "none"; });
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
  document.querySelectorAll(".card").forEach(card => {
    const st = DATA.states[+card.dataset.si];
    card.querySelector(".modestats").innerHTML = modeStatsHtml(st, selOf(card, st));
  });
}

function renderCard(card) {
  const st = DATA.states[+card.dataset.si];
  const sel = selOf(card, st);
  card.querySelectorAll(".chart").forEach(chart => {
    chart.innerHTML = `<div class="rlabel">${RANGE_LABEL[chart.dataset.r]}</div>` + renderChart(st, chart.dataset.r, sel);
  });
  const fc = card.querySelector(".fscount");
  if (fc) fc.textContent = (st.fires || []).filter(isImpactful).length;
}

function renderAll() {
  tip.style.display = "none";
  document.querySelectorAll(".card").forEach(renderCard);
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
    if (!s.length || s.length <= i) return;
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
      const dd = (s, off) => s.length > i && i - off >= 0 ? s[i] - s[i - off] : null;
      const cell = d => {
        if (d === null) return `<td class="zero">–</td>`;
        const v = Math.round(d * 10) / 10;
        return `<td class="${v > 0 ? "pos" : v === 0 ? "zero" : ""}">${v > 0 ? "+" : ""}${v}</td>`;
      };
      const num = v => Math.round(v * 10) / 10;
      const term = (name, sw, s) =>
        `<tr><td class="n"><span class="sw">${sw}</span>${name}</td><td>${num(s[i])}</td>${cell(dd(s, 1))}${cell(dd(s, 7))}</tr>`;
      let body = term("traffic", legendSwatch("traffic"), m.traffic);
      if (m.mode && m.mode.kwSeries) {
        const ranked = m.mode.kwSeries
          .map((s, k) => ({ s, k }))
          .filter(x => x.s.length)
          .sort((a, b) => b.s[i] - a.s[i]);
        ranked.forEach(x => { body += term((m.kws || st.kws)[x.k], legendSwatch(KW_META[x.k]), x.s); });
      } else {
        body += `<tr><td class="n" colspan="4" style="color:var(--muted)">trends not fetched yet</td></tr>`;
      }
      tip.innerHTML = `<div class="d">${m.name} metro</div>
        <table class="tt"><thead><tr><th>series</th><th>${fdate(DATA.dates[i])}</th><th>Δ 1d</th><th>Δ 7d</th></tr></thead>
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

function roll7(s, endI) {
  let sum = 0, n = 0;
  for (let i = Math.max(0, endI - 6); i <= endI; i++) { sum += s[i]; n++; }
  return sum / n;
}

function buildMovers() {
  const metros = allMetros();
  const sec = document.getElementById("movers");
  if (!metros.length) { sec.hidden = true; return; }
  sec.hidden = false;
  const lastFull = N - 2;                       /* Google's final day is partial */
  const kwFilter = +document.getElementById("mkw").value;  /* -1 = any term */
  document.getElementById("mnote").textContent =
    `latest full day: ${fdate(DATA.dates[lastFull])} · values are each metro's own 0–100 search index`;

  const dod = [], high = [];
  metros.forEach(e => {
    let bestD = null, bestH = null;
    e.m.mode.kwSeries.forEach((s, k) => {
      if (kwFilter >= 0 && k !== kwFilter) return;
      if (!s.length || s.length <= lastFull) return;
      const delta = s[lastFull] - s[lastFull - 1];
      if (!bestD || delta > bestD.delta)
        bestD = { ...e, k, delta, from: s[lastFull - 1], to: s[lastFull] };
      const trailing = roll7(s, lastFull);
      let peak = 0;
      for (let i = 6; i <= lastFull; i++) peak = Math.max(peak, roll7(s, i));
      if (peak > 0) {
        const ratio = trailing / peak;
        if (!bestH || ratio > bestH.ratio || (ratio === bestH.ratio && trailing > bestH.trailing))
          bestH = { ...e, k, ratio, trailing, peak };
      }
    });
    if (bestD && bestD.delta > 0) dod.push(bestD);
    if (bestH) high.push(bestH);
  });
  dod.sort((a, b) => b.delta - a.delta);
  high.sort((a, b) => b.ratio - a.ratio || b.trailing - a.trailing);

  const row = (e, i, val) =>
    `<button class="mrow" data-si="${e.si}" data-mi="${e.mi}">
      <span class="rk">${i + 1}</span><span class="mn">${e.m.name}</span><span class="ab">${e.st.abbr}</span>
      <span class="kw">${(e.m.kws || e.st.kws)[e.k]}</span><span class="val">${val}</span></button>`;
  document.getElementById("mdod").innerHTML = dod.length
    ? dod.slice(0, 5).map((e, i) => row(e, i,
        `${Math.round(e.from)} → ${Math.round(e.to)} <span class="up">+${Math.round(e.delta)}</span>`)).join("")
    : `<div class="mempty">no term rose day-over-day</div>`;
  document.getElementById("m7d").innerHTML = high.length
    ? high.slice(0, 5).map((e, i) => row(e, i,
        `7-day avg ${e.trailing.toFixed(0)} · <span class="up">${Math.round(e.ratio * 100)}%</span> of window high`)).join("")
    : `<div class="mempty">no metro trends data yet</div>`;

  sec.querySelectorAll(".mrow").forEach(btn => btn.addEventListener("click", () => {
    const st = DATA.states[+btn.dataset.si];
    if (stateFilter !== "-1" && st && stateFilter !== st.key) {
      stateFilter = st.key;
      document.getElementById("statef").value = st.key;
      applyStateFilter();
    }
    const card = document.querySelector(`.card[data-si="${btn.dataset.si}"]`);
    if (!card) return;
    const ms = card.querySelector(".msel");
    if (ms) { ms.value = btn.dataset.mi; ms.dispatchEvent(new Event("change")); }
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

function initMovers() {
  const sel = document.getElementById("mkw");
  sel.innerHTML = `<option value="-1">any term</option>` +
    KW_TPL_LABEL.map((l, k) => `<option value="${k}">${l}</option>`).join("");
  sel.addEventListener("change", buildMovers);
  buildMovers();
}

/* ---------- hover ---------- */
const tip = document.getElementById("tip");
function attachHover(card) {
  const st = DATA.states[+card.dataset.si];
  card.querySelectorAll(".chart").forEach(chart => chart.addEventListener("pointermove", e => {
    const [r0, r1] = RANGES[chart.dataset.r];
    const svg = chart.querySelector("svg");
    if (!svg) return;
    const r = svg.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width * W;
    if (fx < ML - 6 || fx > W - MR + 6) { hideTip(svg); return; }
    const i = Math.max(r0, Math.min(r1, Math.round(r0 + (fx - ML) / IW * (r1 - r0))));
    const xi = ML + ((i - r0) / (r1 - r0)) * IW;
    const xh = svg.querySelector(".xh");
    xh.setAttribute("x1", xi); xh.setAttribute("x2", xi); xh.setAttribute("opacity", "0.55");
    const sel = selOf(card, st);
    const { traf, kwS, kws, k25, label } = viewOf(st, sel);
    let rows = "";
    if (visible.traffic && traf)
      rows += `<div class="row"><span class="n">${legendSwatch("traffic")} traffic</span><span class="v">${traf[i]} users</span></div>`;
    if (kwS) kwS.forEach((s, k) => {
      if (!visible["k"+k] || !s.length) return;
      const v25 = k25 && k25[k] && k25[k].length ? `<span style="color:var(--muted)"> · ’25 ${k25[k][i]}</span>` : "";
      rows += `<div class="row"><span class="n">${legendSwatch(KW_META[k])} ${kws[k]}</span><span class="v">${s[i]}${v25}</span></div>`;
    });
    if (visible.fires) {
      const todays = fireMap(st)[i] || [];
      todays.slice(0, 6).forEach(f => {
        const imp = isImpactful(f);
        const pop = f.p ? `${fmt(f.p[impact.ring])} ppl ≤${impact.ring}mi` : "pop n/a";
        rows += `<div class="row"><span class="n">${legendSwatch(imp ? "fires" : "fires_h")} ${f.t} started</span><span class="v">${f.a ? fmt(f.a) + " ac" : ""} · ${pop}</span></div>`;
      });
      if (todays.length > 6) rows += `<div class="row"><span class="n" style="color:var(--muted)">+${todays.length - 6} more fires</span></div>`;
    }
    tip.innerHTML = `<div class="d">${st.name} · ${fdateY(DATA.dates[i])} · ${label}</div>` + rows;
    tip.style.display = "block";
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let tx = e.clientX + 14, ty = e.clientY + 12;
    if (tx + tw > innerWidth - 8) tx = e.clientX - tw - 14;
    if (ty + th > innerHeight - 8) ty = e.clientY - th - 12;
    tip.style.left = tx + "px"; tip.style.top = ty + "px";
  }));
  card.querySelectorAll(".chart").forEach(chart =>
    chart.addEventListener("pointerleave", () => hideTip(chart.querySelector("svg"))));
}
function hideTip(svg) {
  tip.style.display = "none";
  if (svg) { const xh = svg.querySelector(".xh"); if (xh) xh.setAttribute("opacity", "0"); }
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
initMovers();
renderAll();
</script>
"""

html = HTML.replace("__DATA__", json.dumps(payload, separators=(",", ":"))).replace("__GENERATED__", generated)
with open(OUT, "w") as f:
    f.write(html)
n_traffic = sum(1 for s in states_payload if s["stats"])
print(f"wrote {OUT} ({len(html)//1024} KB): {len(states_payload)} states "
      f"({n_traffic} with traffic, {len(states_payload)-n_traffic} trends-only)")
