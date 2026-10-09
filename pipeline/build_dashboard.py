"""Build the self-contained dashboard HTML.

Inputs: site_traffic.json (per-state daily users), trends_data.json (Google
Trends, geo=US-{abbr}, in-state), trends_data_national.json (geo=US),
trends_demand.json (the newer tabs' Google Trends terms), gsc_daily.json (Search Console).
Output: dashboard.html. The "States in Play", "State Page Health" and "Fire Page Health" tabs' code lives in
tabs/{states,health}.{js,css} and is inlined here. DASHBOARD_OUT / DASHBOARD_TABS env vars
redirect the output / limit which tab files are inlined (for test builds).
"""
import json, math, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("DASHBOARD_OUT") or os.path.join(BASE, "dashboard.html")   # override: test builds

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
tr_demand = load_opt("trends_demand.json")   # "states in play" / "review health" terms (fetch_trends.py demand)
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

# ---- demand terms for the new tabs: {kws, s} per area, s = one daily series per term on the
# dashboard axis (None = no Google value that day); each area's terms share one 0-100 scale ----
demand_payload = None
if tr_demand:
    def demand_entry(e):
        idx = {d: i for i, d in enumerate(e["dates"])}
        ser = [[(lambda k: float(e["series"][kw][k]) if k is not None and k < len(e["series"][kw]) else None)(idx.get(d))
                for d in dates] for kw in e["keywords"]]
        return {"kws": e["keywords"], "kwSeries": ser}
    d_entries = {k: demand_entry(e) for k, e in tr_demand["states"].items() if e.get("dates")}
    null_dropouts(list(d_entries.values()), "demand trends")
    demand_payload = {
        "timeframe": tr_demand["meta"]["timeframe"],
        "national": ({"kws": d_entries["national"]["kws"], "s": d_entries["national"]["kwSeries"]}
                     if "national" in d_entries else None),
        "states": {k: {"kws": v["kws"], "s": v["kwSeries"]} for k, v in d_entries.items() if k != "national"},
    }
    print(f"demand trends: national {'yes' if demand_payload['national'] else 'no'}, "
          f"{len(demand_payload['states'])} states ({demand_payload['timeframe']})")

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
        return {f: [t[f][k] if k is not None else None for k in pos] for f in ("c", "i", "p", "b", "bq", "bi") if f in t}

    in_window = lambda t: any((v or 0) > 0 for v in galign(t)["i"])

    def tracked_align(tr):
        """tracked searches (queries containing all the words of one of the area's demand terms) on the
        dashboard axis: {terms, topFrom, all|page|fire: {any, terms: [4], top: [[query, impressions, clicks]]}}"""
        out = {"terms": tr["terms"], "topFrom": tr["top_from"]}
        for scope in ("all", "page", "fire"):
            if tr.get(scope):
                out[scope] = {"any": galign(tr[scope]["any"]) if tr[scope]["any"] else None,
                              "terms": [galign(t) if t else None for t in tr[scope]["terms"]],
                              "top": tr[scope]["top"]}
        return out
    for sp in states_payload:
        g = gsc_raw["states"].get(sp["key"])
        if not g:
            continue
        sp["gsc"] = {t: galign(v) for t, v in g["types"].items() if in_window(v)}
        if g.get("state_page"):
            sp["gscPage"] = galign(g["state_page"])   # the state's own page alone (web)
        if g.get("fire_pages"):
            sp["gscFire"] = galign(g["fire_pages"])   # the state's fire pages alone, no state page (web)
        if g.get("tracked"):
            sp["gscTracked"] = tracked_align(g["tracked"])
        for mp in sp["metros"]:
            mg = g["metros"].get(mp["key"])
            if mg:
                mp["gsc"] = {t: galign(v) for t, v in mg.items() if in_window(v)}
    gm = gsc_raw["meta"]
    gsc_payload = {
        "property": gm["property"], "pageFilter": gm["page_filter"], "exportedAt": gm["exported_at"],
        "lastDate": gm["last_date"], "lastComplete": gm["last_complete_date"], "coveredFrom": gm.get("covered_from"),
        "bestMin": gm.get("best_min_impr", 20), "bestDays": gm.get("best_days", 1),
        "types": [t for t in gm["types"] if any(t in (sp.get("gsc") or {}) for sp in states_payload)],
        "topWindow": gm["top_window"], "prevWindow": gm["prev_window"],
        "topQueries": gsc_raw["top_queries"],
        "site": galign(gsc_raw["site"]["web"]) if gsc_raw["site"].get("web") else None,   # every page (web)
        "home": galign(gsc_raw["home"]) if gsc_raw.get("home") else None,                 # homepage alone (web)
        "fireNational": galign(gsc_raw["fire_pages"]) if gsc_raw.get("fire_pages") else None,  # every fire page (web)
        "trackedNational": tracked_align(gsc_raw["tracked"]) if gsc_raw.get("tracked") else None,
    }
    print(f"search console: {gm['property']} through {gm['last_date']} (complete through {gm['last_complete_date']}), "
          f"types {gsc_payload['types']}, {sum(1 for sp in states_payload if sp.get('gsc'))} states, "
          f"{sum(1 for sp in states_payload for mp in sp['metros'] if mp.get('gsc'))} metro slices")

payload = {"dates": dates, "timeframe": tr_state["meta"]["timeframe"],
           "has25": bool(tr25_state or tr25_natl), "hasNatl": bool(tr_natl),
           "fetchedAt": fetched_at, "states": states_payload, "maps": maps, "gsc": gsc_payload,
           "demand": demand_payload}
generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ")

HTML = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>WFE SEO Dashboard</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%232f6153'/%3E%3Cpolyline points='4,18 10,18 13,10 18.5,25 21.5,18 28,18' fill='none' stroke='%23f6e7cf' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..700&family=Figtree:ital,wght@0,400..700;1,400..600&display=swap">
<style>
  /* Layout: a warm sand page with paper-white cards for real sections only. One juniper accent marks
     everything you can click; semantic good/bad colors and chart series never borrow it.
     Single light theme by design (no dark mode). Every color is a token below; components and
     JS-generated SVG use only these. Full rules: scratchpad/redesign/DESIGN.md */
  :root {
    color-scheme: light;
    /* ground + ink */
    --bg: #f3ede3;            /* page ground: warm sand */
    --surface: #fffcf7;       /* cards, popovers, chart plot area: warm paper */
    --surface-2: #f8f3eb;     /* quiet inset fill: empty states, summary rows, hover on paper controls */
    --ink: #2b2620;           /* primary text: warm charcoal-brown (14.6:1 on surface) */
    --ink-2: #5c5248;         /* secondary text, table headers, notes (7.4:1) */
    --muted: #766a5e;         /* captions, axis labels, hints (5.1:1 on surface, 4.5:1 on bg) */
    --border: #e4dacb;        /* card edges, block dividers */
    --line: #eee6da;          /* table row hairlines */
    --control-border: #d5c8b5;/* buttons, selects, inputs: just enough edge to read as a control */
    --grid: #ece4d8;          /* chart gridlines */
    --axis: #cfc2af;          /* chart baseline, the "1x" reference lines, group-header rules */
    --chip-bg: rgba(110, 86, 56, .07);   /* hover / highlighted-row tint; works on bg and surface */
    --tooltip-bg: #fffcf7;
    --shadow-card: 0 1px 2px rgba(74, 56, 36, .05);
    --shadow-pop: 0 2px 6px rgba(74, 56, 36, .08), 0 12px 32px rgba(74, 56, 36, .16);
    /* the one interactive accent: deep juniper */
    --accent: #2f6153;        /* selected tab, focus ring, active pill, links (6.9:1 on surface) */
    --accent-strong: #244c41; /* hover / pressed, text on --accent-soft */
    --accent-soft: #e1ece5;   /* quiet selected fills (preset list, range days, open popover button) */
    --accent-ink: #fffcf7;    /* text on a solid --accent fill */
    --fm: var(--accent);      /* legacy name, still used for focus rings in tabs/*.css */
    --range-bg: var(--accent-soft);   /* date picker: days inside the range */
    /* semantic state (separate from the accent; always paired with a label) */
    --good: #4a7a2c;          /* leaf green: up arrows, "outperforming" marks (5.0:1) */
    --good-soft: #e5edd8;     /* good pill background */
    --good-ink: #3d6a22;      /* text on --good-soft (5.3:1) */
    --bad: #a3412c;           /* brick red: down arrows, "missing demand" marks (6.1:1) */
    --bad-soft: #f7e2da;
    --bad-ink: #8c3423;       /* text on --bad-soft (6.4:1) */
    --neutral: #8a7e71;       /* warm grey marks: "tracking", "low signal" dots */
    --neutral-soft: #eee7dc;
    --neutral-ink: #5c5248;   /* text on --neutral-soft (6.2:1) */
    /* chart series: meaning unchanged, values validated on --surface (all >= 3:1; see DESIGN.md) */
    --traffic: #297613;       /* our traffic / clicks (forest green, drawn with an area wash) */
    --traffic-fill: rgba(41, 118, 19, .12);
    --gi: #3246a9;            /* Search Console impressions (indigo: darker and bluer than the green, so the two never blur) */
    --demand: #bd8630;        /* health tabs: combined Google Trends search demand (ochre; no fire markers share those charts) */
    --gc: #a34a7c;            /* Search Console CTR (berry) */
    --gp: #54493e;            /* Search Console avg + best position (umber; dotted / dashed) */
    --f: #049e98;             /* Trends: fire {state} = search demand (teal) */
    --wf: #a68f37;            /* Trends: wildfire {state} (mustard) */
    --fn: #957fd6;            /* Trends: fire near me / {city} (lavender) */
    --fire-mk: #de7431;       /* fire starts (ember) */
    /* type */
    --font-display: "Bricolage Grotesque", "Figtree", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    --font-ui: "Figtree", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    --fs-h1: 26px; --fs-h2: 19px; --fs-h3: 15px; --fs-body: 15px; --fs-table: 14px;
    --fs-small: 13px; --fs-pill: 12.5px; --fs-axis: 11.5px;
    /* spacing + shape */
    --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 24px; --sp-6: 32px; --sp-7: 48px;
    --r-sm: 6px; --r-md: 10px; --r-lg: 14px; --r-pill: 999px;
    --read: 72ch;             /* reading width for notes and explanations */
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: var(--font-ui);
    font-size: var(--fs-body);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  /* every chart label, whatever its font-family attribute says: the UI face with aligned digits */
  svg text { font-family: var(--font-ui); font-variant-numeric: tabular-nums; }
  /* a paper halo so a line crossing a chart label never cuts through it (opt in elsewhere with class="halo") */
  .chart svg text, .quad svg text, svg text.halo { paint-order: stroke; stroke: var(--surface); stroke-width: 3px; stroke-linejoin: round; }
  /* a direct label a spike can run through (the traffic peak): a wider halo that also closes the word gap */
  .chart svg text.pk { stroke-width: 7px; }
  a { color: var(--accent); text-underline-offset: 3px; }
  a:hover { color: var(--accent-strong); }
  b, strong { font-weight: 600; }
  h1, h2, h3 { text-wrap: balance; }
  .wrap { max-width: 1440px; margin: 0 auto; padding-block: var(--sp-6) 72px; padding-inline: clamp(16px, 3vw, 32px); }

  /* ---- page header + top-level tabs ---- */
  /* the title and the tabs stay pinned at the top; on wide screens they share one row */
  .topbar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 7; display: flex; flex-wrap: wrap;
    align-items: flex-end; gap: 0 var(--sp-6); margin: calc(-1 * var(--sp-6)) calc(-1 * var(--sp-4)) var(--sp-5);
    padding: var(--sp-4) var(--sp-4) 0; background: var(--bg); border-bottom: 1px solid var(--border); }
  h1 { font-family: var(--font-display); font-size: var(--fs-h1); font-weight: 700; letter-spacing: -0.015em;
    line-height: 1.2; margin: 0; padding-bottom: 12px; color: var(--ink); }
  @media (max-width: 899px) {
    .topbar { padding-top: var(--sp-3); }
    .topbar h1 { flex-basis: 100%; font-size: 21px; padding-bottom: 2px; }
  }
  nav.tabs { display: flex; gap: var(--sp-1); min-width: 0; max-width: 100%;
    overflow-x: auto; scrollbar-width: none; }
  nav.tabs::-webkit-scrollbar { display: none; }
  nav.tabs button { font: inherit; font-size: 15px; font-weight: 600; color: var(--ink-2); background: none; border: 0;
    border-bottom: 3px solid transparent; border-radius: var(--r-sm) var(--r-sm) 0 0; padding: 10px 14px 9px;
    margin-bottom: -1px; cursor: pointer; white-space: nowrap; }
  nav.tabs button:hover { color: var(--ink); background: var(--chip-bg); }
  nav.tabs button[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); background: none; }
  nav.tabs button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

  /* ---- buttons, chips, selects ---- */
  .controls {
    position: sticky; top: calc(env(safe-area-inset-top, 0px) + var(--top-h, 0px)); z-index: 5;
    display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2);
    padding: var(--sp-3) var(--sp-4); margin: 0 calc(-1 * var(--sp-4)) var(--sp-5);
    background: var(--bg);
    border-bottom: 1px solid var(--border);
  }
  .seg { display: inline-flex; border: 1px solid var(--control-border); border-radius: var(--r-pill); overflow: hidden;
    background: var(--surface); margin-right: var(--sp-1); }
  .seg button { font: inherit; font-size: 14px; padding: 6px 14px; cursor: pointer; border: 0; background: transparent; color: var(--ink-2); }
  .seg button.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; }
  .seg button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  /* .lg = a rounded button or toggle chip; legend chips carry the series swatch first */
  .lg {
    display: inline-flex; align-items: center; gap: var(--sp-2);
    min-height: 34px; padding: 5px 14px 5px 11px; border-radius: var(--r-pill);
    border: 1px solid var(--control-border); background: var(--surface);
    color: var(--ink); font: inherit; font-size: 14px; font-weight: 500; line-height: 1.3; cursor: pointer;
  }
  .lg:hover { border-color: var(--axis); background: var(--surface-2); }
  .lg:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .lg.off { background: transparent; color: var(--muted); border-style: dashed; }
  .lg.off svg { opacity: .35; }
  .lg svg { display: block; flex: none; }
  .impact { display: inline-flex; align-items: center; gap: var(--sp-2); font-size: 14px; color: var(--ink-2);
    border: 1px solid var(--control-border); border-radius: var(--r-pill); padding: 5px 14px; background: var(--surface); }
  .impact input[type=range] { width: 88px; accent-color: var(--accent); margin: 0; }
  .impact b { font-weight: 600; color: var(--ink); min-width: 42px; text-align: center; font-variant-numeric: tabular-nums; }
  :is(.controls, .lgbar) .gap { flex: 1; }
  :is(.controls, .lgbar) .cbreak { flex-basis: 100%; height: 0; }
  /* the chart legend above the state cards: each series is a pill toggle (paper when shown,
     dashed + faded when hidden), plus the chart-only options (smoothing, fire settings) */
  .lgbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2);
    padding: var(--sp-3) var(--sp-4); margin: 0 calc(-1 * var(--sp-4)) var(--sp-4);
    background: var(--bg); border-bottom: 1px solid var(--border); }
  @media (min-width: 701px) { .lgbar { position: sticky; top: calc(env(safe-area-inset-top, 0px) + var(--top-h, 0px) + var(--ctrl-h, 0px)); z-index: 4; } }
  .lgbar .lgkey { color: var(--ink-2); font-size: 14px; font-weight: 600; margin-right: var(--sp-1); }
  .lgt { display: inline-flex; align-items: center; gap: var(--sp-2); min-height: 34px; padding: 5px 14px 5px 11px;
    border: 1px solid var(--control-border); border-radius: var(--r-pill); background: var(--surface); color: var(--ink);
    font: inherit; font-size: 14px; font-weight: 500; line-height: 1.3; cursor: pointer; }
  .lgt:hover { border-color: var(--axis); background: var(--surface-2); }
  .lgt:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .lgt svg { display: block; flex: none; }
  .lgt.off { background: transparent; border-style: dashed; border-color: var(--axis); color: var(--muted); }
  .lgt.off svg { opacity: .3; }
  .lgt.off:hover { background: var(--chip-bg); color: var(--ink-2); }
  .lgroup { color: var(--muted); font-size: var(--fs-small); margin: 0 0 0 var(--sp-3); padding-left: var(--sp-3);
    border-left: 1px solid var(--control-border); line-height: 1.2; }
  .popbody .lghead { font-size: var(--fs-small); color: var(--muted); white-space: normal; max-width: 260px; }
  /* inside the Search terms popover the toggles read as a checklist */
  .popbody .lgt { position: relative; min-height: 30px; padding: 3px 10px 3px 32px; margin-left: -8px; border: 0;
    background: transparent; color: var(--ink); text-align: left; white-space: nowrap; }
  .popbody .lgt:hover { background: var(--chip-bg); }
  .popbody .lgt::before { content: ""; position: absolute; left: 8px; top: 50%; width: 16px; height: 16px; margin-top: -8px;
    border: 1.5px solid var(--control-border); border-radius: 4px; background: var(--surface); box-sizing: border-box; }
  .popbody .lgt[aria-pressed="true"]::before { background: var(--accent); border-color: var(--accent); }
  .popbody .lgt[aria-pressed="true"]::after { content: ""; position: absolute; left: 14px; top: 50%; width: 4px; height: 8px; margin-top: -6px;
    border-right: 2px solid var(--accent-ink); border-bottom: 2px solid var(--accent-ink); transform: rotate(45deg); }
  .popbody .lgt.off { color: var(--ink); }
  .popbody .lgt.off svg { opacity: 1; }
  /* chevron for dropdown buttons, drawn like the selects' */
  .chev { flex: none; width: 7px; height: 7px; margin: 0 2px 3px 2px; border-right: 1.5px solid var(--ink-2);
    border-bottom: 1.5px solid var(--ink-2); transform: rotate(45deg); }
  .dbtn { font-variant-numeric: tabular-nums; color: var(--ink); font-weight: 600; }
  .dbtn .lbl { color: var(--muted); font-weight: 400; margin-left: 2px; }
  .popbody .ptitle { display: flex; align-items: center; gap: var(--sp-2); font-size: 14px; font-weight: 600; color: var(--ink); }
  .lgt .lbl { color: var(--muted); font-weight: 400; }
  .popbody .pnote { font-size: var(--fs-small); color: var(--muted); max-width: 300px; white-space: normal; margin-top: calc(-1 * var(--sp-2)); }
  .popbody .prow .plab { min-width: 52px; }
  /* every dropdown: one look (pill edge, token-drawn chevron) */
  select.sel, .statef, .card h2 .msel, .qhead select, .movers .mhead select, .popbody select, .impact select {
    appearance: none; -webkit-appearance: none;
    font: inherit; font-size: 14px; font-weight: 500; line-height: 1.3; color: var(--ink);
    min-height: 34px; padding: 6px 34px 6px 14px; margin: 0;
    background-color: var(--surface);
    /* a thin line chevron, the same as .chev on popover buttons: two 5px tiles, one diagonal each */
    background-image:
      linear-gradient(to top right, transparent calc(50% - 1px), var(--ink-2) calc(50% - .6px), var(--ink-2) calc(50% + .6px), transparent calc(50% + 1px)),
      linear-gradient(to bottom right, transparent calc(50% - 1px), var(--ink-2) calc(50% - .6px), var(--ink-2) calc(50% + .6px), transparent calc(50% + 1px));
    background-position: calc(100% - 20px) 50%, calc(100% - 15px) 50%;
    background-size: 5px 5px, 5px 5px; background-repeat: no-repeat;
    border: 1px solid var(--control-border); border-radius: var(--r-pill); cursor: pointer;
    max-width: 100%; text-overflow: ellipsis;
  }
  select.sel:hover, .statef:hover, .card h2 .msel:hover, .qhead select:hover, .movers .mhead select:hover { border-color: var(--axis); background-color: var(--surface-2); }
  select.sel:focus-visible, .statef:focus-visible, .card h2 .msel:focus-visible, .qhead select:focus-visible,
  .movers .mhead select:focus-visible, .popbody select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .statef { font-weight: 600; }
  .smooth { display: inline-flex; align-items: center; gap: var(--sp-2); color: var(--ink-2); font-size: 14px; cursor: pointer; }
  .smooth input { accent-color: var(--accent); width: 16px; height: 16px; margin: 0; }
  .axis-note { width: 100%; color: var(--muted); font-size: var(--fs-small); padding-top: 2px; }

  /* ---- popovers (details.pop) + the date-range picker ---- */
  details.pop { position: relative; }
  details.pop > summary { list-style: none; cursor: pointer; }
  details.pop > summary::-webkit-details-marker { display: none; }
  details.pop[open] > summary.lg { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-strong); }
  details.pop .popbody {
    position: absolute; top: calc(100% + 8px); left: 0; z-index: 30;
    display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-3);
    background: var(--tooltip-bg); border: 1px solid var(--border); border-radius: 12px;
    box-shadow: var(--shadow-pop); padding: var(--sp-3) var(--sp-4); min-width: 260px;
  }
  details.pop-r .popbody { left: auto; right: 0; }
  .popbody .prow { display: flex; flex-wrap: nowrap; align-items: center; gap: var(--sp-2); font-size: 14px; color: var(--ink-2); white-space: nowrap; }
  .popbody .prow input[type=range] { width: 96px; flex: 0 1 96px; min-width: 64px; margin: 0; accent-color: var(--accent); }
  .popbody .prow b { font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums; }
  details.pop.dpick .popbody { flex-direction: row; align-items: flex-start; gap: var(--sp-4); padding: var(--sp-4); }
  .dpresets { display: flex; flex-direction: column; gap: 2px; min-width: 132px; }
  .dpresets button { font: inherit; font-size: 14px; text-align: left; padding: 7px 12px; border: 0; border-radius: 8px;
    background: transparent; color: var(--ink-2); cursor: pointer; white-space: nowrap; }
  .dpresets button:hover { background: var(--chip-bg); color: var(--ink); }
  .dpresets button.on { background: var(--accent-soft); color: var(--accent-strong); font-weight: 600; }
  .dcals { display: flex; gap: var(--sp-5); border-left: 1px solid var(--border); padding-left: var(--sp-4); }
  .dcal { width: 238px; }
  .dchead { font-size: var(--fs-small); color: var(--muted); margin-bottom: var(--sp-2); }
  .dchead b { color: var(--ink); font-weight: 600; font-size: 14px; margin-left: 4px; }
  .dcnav { display: flex; align-items: center; justify-content: space-between; font-size: 14px; font-weight: 600;
    color: var(--ink); margin-bottom: 6px; }
  .dnav { font: inherit; font-size: 17px; line-height: 1; width: 30px; height: 30px; border: 1px solid var(--control-border);
    border-radius: 8px; background: var(--surface); color: var(--ink-2); cursor: pointer; }
  .dnav:hover:not(:disabled) { background: var(--surface-2); color: var(--ink); }
  .dnav:disabled { opacity: .35; cursor: default; }
  .dgrid { display: grid; grid-template-columns: repeat(7, 1fr); row-gap: 2px; }
  .dgrid .dow { font-size: 12px; font-weight: 600; color: var(--muted); text-align: center; padding: 2px 0 6px; }
  .dday { font: inherit; font-size: 13.5px; height: 32px; padding: 0; border: 0; border-radius: 0; background: transparent;
    color: var(--ink); cursor: pointer; font-variant-numeric: tabular-nums; }
  .dday:hover:not(:disabled) { box-shadow: inset 0 0 0 1.5px var(--accent); border-radius: 8px; }
  .dday:disabled { color: var(--axis); cursor: default; }
  .dday.in { background: var(--range-bg); }
  .dday.rs { border-radius: 8px 0 0 8px; }
  .dday.re { border-radius: 0 8px 8px 0; }
  .dday.rs.re, .dday.pick { border-radius: 8px; }
  .dday.pick { background: var(--accent); color: var(--accent-ink); font-weight: 600; }
  .dday:focus-visible, .dnav:focus-visible, .dpresets button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .card, .mapcard { scroll-margin-top: calc(var(--top-h, 0px) + var(--ctrl-h, 0px) + var(--lg-h, 0px) + 12px); }
  .tabpane { scroll-margin-top: var(--top-h, 0px); }
  @media (max-width: 700px) {
    .controls, .lgbar { position: relative; top: auto; }   /* the sticky offset would push a relative bar over the first heading */
    /* phone: a control's popover spans the bar's content width under its button, so it never runs off-screen */
    :is(.controls, .lgbar) details.pop { position: static; }
    :is(.controls, .lgbar) details.pop .popbody { left: var(--sp-4); right: var(--sp-4); min-width: 0; top: auto; margin-top: var(--sp-2); }
    .controls details.pop.dpick .popbody { align-items: stretch; max-width: none; }
    .controls details.pop.dpick .dcal { width: auto; }
    .lgroup { flex-basis: 100%; margin: var(--sp-1) 0 0; padding: 0; border: 0; }
    details.pop.dpick .popbody { flex-direction: column; max-width: calc(100vw - 32px); }
    .dpresets { flex-direction: row; flex-wrap: wrap; }
    .dcals { flex-direction: column; border-left: 0; padding-left: 0; border-top: 1px solid var(--border); padding-top: var(--sp-3); }
  }

  /* ---- disclosure: long explanations live here, closed by default ----
     <details class="about"><summary>How this is calculated</summary><div class="about-body"><p>…</p></div></details> */
  details.about { margin-top: var(--sp-4); }
  details.about > summary {
    display: inline-flex; align-items: center; gap: var(--sp-2); list-style: none; cursor: pointer;
    color: var(--ink-2); font-size: 14px; font-weight: 600; line-height: 1.3;
    padding: 6px 12px 6px 8px; margin-left: -8px; border-radius: 8px;
  }
  details.about > summary::-webkit-details-marker { display: none; }
  details.about > summary::before {
    content: ""; flex: none; width: 6px; height: 6px; margin: 0 3px 2px 2px;
    border-right: 2px solid currentColor; border-bottom: 2px solid currentColor;
    transform: rotate(-45deg); transition: transform .15s ease;
  }
  details.about[open] > summary::before { transform: rotate(45deg); margin-bottom: 4px; }
  details.about > summary:hover, details.about[open] > summary { color: var(--accent); }
  details.about > summary:hover { background: var(--accent-soft); }
  details.about > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 0; }
  details.about .about-body { padding: var(--sp-2) 0 var(--sp-1) 19px; max-width: calc(var(--read) + 19px);
    color: var(--ink-2); font-size: 14px; line-height: 1.6; }
  .about-body > :first-child { margin-top: 0; }
  .about-body p, .about-body ul, .about-body dl { margin: 0 0 var(--sp-3); }
  .about-body ul { padding-left: 1.2em; }
  .about-body li { margin-bottom: var(--sp-1); }
  .about-body h4 { font-size: 15px; font-weight: 650; color: var(--ink); margin: var(--sp-5) 0 var(--sp-2); }
  .about-body dt { font-size: 14px; }
  .about-body dt { font-weight: 600; color: var(--ink); }
  .about-body dd { margin: 0 0 var(--sp-2); }
  .about-body b { color: var(--ink); }
  @media (prefers-reduced-motion: reduce) { details.about > summary::before { transition: none; } }

  /* ---- sections: one card per real section ---- */
  .panel, .overview, .movers, .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg);
    box-shadow: var(--shadow-card); padding: var(--sp-5); margin-bottom: var(--sp-5); min-width: 0;
  }
  .card { margin-bottom: 0; }
  .panel h2, .overview h2, .movers .mhead h2 {
    font-family: var(--font-display); font-size: var(--fs-h2); font-weight: 650; letter-spacing: -0.01em;
    line-height: 1.25; margin: 0 0 var(--sp-1); color: var(--ink);
  }
  .panel .psub, .overview .osub { color: var(--ink-2); font-size: 14px; line-height: 1.5; margin-bottom: var(--sp-4); max-width: var(--read); }
  .panel h3, .ocol h3, .mcol h3 { font-family: var(--font-ui); font-size: var(--fs-h3); font-weight: 600; color: var(--ink);
    margin: 0 0 var(--sp-2); text-transform: none; letter-spacing: 0; }
  .tbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2) var(--sp-3); margin: 0 0 var(--sp-5); }
  /* the newer tabs' filter bars pin under the title and tabs, like the Overview's controls (desktop; phones scroll them away) */
  @media (min-width: 701px) {
    :is(#pane-states, #pane-hpage, #pane-hall) > .tbar { position: sticky; top: calc(env(safe-area-inset-top, 0px) + var(--top-h, 0px));
      z-index: 5; margin-inline: calc(-1 * var(--sp-4)); padding: var(--sp-3) var(--sp-4); background: var(--bg);
      border-bottom: 1px solid var(--border); }
  }
  .tbar .tlabel { color: var(--muted); font-size: var(--fs-small); }
  .tabnotes { margin-top: var(--sp-5); color: var(--ink-2); font-size: 14px; line-height: 1.6; max-width: var(--read); }
  .tabnotes p { margin: 0 0 var(--sp-3); }
  /* a heading that introduces a run of cards, sitting on the page ground rather than in a card */
  .sechead { margin: var(--sp-6) 0 var(--sp-4); }
  .sechead h2 { font-family: var(--font-display); font-size: var(--fs-h2); font-weight: 650; letter-spacing: -0.01em;
    line-height: 1.25; margin: 0 0 var(--sp-1); color: var(--ink); }
  .sechead .psub { color: var(--ink-2); font-size: 14px; max-width: var(--read); }
  .sechead details.about { margin-top: var(--sp-2); }
  /* "how to read" key: a swatch column and its meaning */
  .about-body dl.key { display: grid; grid-template-columns: auto 1fr; gap: var(--sp-2) var(--sp-3); align-items: baseline; }
  .about-body dl.key dt { display: inline-flex; align-items: center; gap: var(--sp-2); white-space: nowrap; }
  .about-body dl.key dt svg { flex: none; align-self: center; }
  /* the key sits on the sand ground; a paper tile behind each swatch keeps the lighter series at chart contrast */
  .sechead .about-body dl.key svg { background: var(--surface); border-radius: 3px; box-shadow: 0 0 0 2px var(--surface); }
  .about-body dl.key dd { margin: 0; }
  .about-body dl.tags { display: grid; grid-template-columns: max-content 1fr; gap: var(--sp-2) var(--sp-3); align-items: baseline; }
  .about-body dl.tags dd { margin: 0; }
  @media (max-width: 600px) {
    .about-body dl.key, .about-body dl.tags { grid-template-columns: 1fr; gap: 0; }
    .about-body dl.tags dd { margin-bottom: var(--sp-2); }
    .about-body dl.key dd { margin-bottom: var(--sp-2); }
  }
  .mempty { color: var(--muted); font-size: 14px; padding: var(--sp-3) 0; }
  .mcol .mempty { color: var(--muted); font-size: 14px; padding: var(--sp-3) 0; }

  /* ---- status pills: soft tint + darker text of the same hue; the label carries the state, so it never rides on color alone ---- */
  .pill {
    display: inline-flex; align-items: center; gap: 6px; vertical-align: middle;
    border-radius: var(--r-pill); padding: 2px 10px;
    font-size: var(--fs-pill); font-weight: 600; line-height: 1.45; white-space: nowrap;
    background: var(--neutral-soft); color: var(--neutral-ink);
  }
  .pill.st-out { background: var(--good-soft); color: var(--good-ink); }
  .pill.st-track { background: var(--neutral-soft); color: var(--neutral-ink); }
  .pill.st-miss { background: var(--bad-soft); color: var(--bad-ink); }
  .pill.st-low { background: transparent; color: var(--muted); border: 1px solid var(--line); padding: 1px 9px; }

  /* ---- Overview pieces (restructured by the Overview pass; restyled here to the shared look) ---- */
  .ocols { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--sp-6); }
  /* status counts above the table */
  .ssum { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); margin: 0 0 var(--sp-5); }
  .ssum .slead { color: var(--ink-2); font-size: 14px; font-weight: 600; margin-right: var(--sp-1); }
  .ssum .pill { font-size: 13px; padding: 3px 12px; }
  .ssum .pill.st-low { padding: 2px 11px; }
  .ssum .sumlow { cursor: help; }
  .ssum .sumlow:hover { border-color: var(--muted); }
  .ssum .sumlow:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  #tip .lowg { margin-top: var(--sp-2); }
  #tip .lowg .tnote { margin: 0 0 var(--sp-1); max-width: 320px; }
  .ssum .snone { color: var(--ink-2); font-size: 14px; }
  .quad .qbody { display: flex; flex-wrap: wrap; gap: var(--sp-4) var(--sp-6); align-items: flex-start; }
  .quad #oquad { flex: 0 1 470px; min-width: 0; }
  .quad .qside { flex: 1 1 280px; max-width: var(--read); padding-top: var(--sp-2); }
  .quad .qside .qq { margin: 0 0 var(--sp-3); color: var(--ink-2); font-size: 14px; }
  .quad .qside details.about { margin-top: var(--sp-3); }
  .qlegend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--ink-2); }
  .qlegend li { display: flex; align-items: center; gap: var(--sp-2); }
  .qlegend svg { flex: none; overflow: visible; }
  .qhead { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2) var(--sp-4); margin-bottom: var(--sp-3); }
  .qhead h3 { margin: 0; }
  .qhead .qsel { display: inline-flex; align-items: center; gap: var(--sp-2); color: var(--muted); font-size: var(--fs-small); }
  /* wide tables scroll sideways inside .hsin; .hscroll fades the right edge while there's more to see */
  .hscroll { position: relative; }
  .hsin { overflow-x: auto; }
  .hscroll::after { content: ""; position: absolute; top: 0; right: 0; bottom: 0; width: 36px; pointer-events: none;
    background: linear-gradient(to right, transparent, var(--surface)); opacity: 0; transition: opacity .15s ease; }
  .hscroll.more::after { opacity: 1; }
  .hscroll .swipe { display: none; color: var(--muted); font-size: var(--fs-small); margin: 0 0 var(--sp-2); }
  @media (max-width: 700px) { .hscroll.wide .swipe { display: block; } }
  .mtab.score { min-width: 720px; }
  .mtab td.why { white-space: normal; }
  .mtab.score th.l.why, .mtab.score td.why { padding-left: 22px; }
  .mtab td.why .whyk { color: var(--ink); font-weight: 600; }
  .mtab td.why .whyd { display: block; color: var(--muted); font-size: var(--fs-small); line-height: 1.4; margin-top: 1px; }
  .mtab td.why .whys { color: var(--ink-2); }
  .mtab th .thsub { display: block; color: var(--muted); font-weight: 400; font-size: 12px; white-space: nowrap; margin-top: 1px; }
  .mtab th .thsub::first-letter { text-transform: none; }
  .sline { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); margin-top: var(--sp-3); font-size: 14px; }
  .sline .slabel { color: var(--ink); font-size: 14px; font-weight: 600; white-space: nowrap; }
  .sline .lbl { color: var(--muted); }
  details.sline > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline; gap: var(--sp-2); width: 100%;
    padding: var(--sp-1) 0; }
  details.sline > summary::-webkit-details-marker { display: none; }
  details.sline > summary::before { content: ""; flex: none; align-self: center; width: 6px; height: 6px; margin: 0 4px 0 2px;
    border-right: 2px solid var(--ink-2); border-bottom: 2px solid var(--ink-2); transform: rotate(-45deg); }
  details.sline[open] > summary::before { transform: rotate(45deg); }
  details.sline > summary:hover .slabel { color: var(--accent); }
  details.sline > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-sm); }
  details.sline[open] { padding-bottom: var(--sp-1); }
  .schip { font: inherit; font-size: 13px; font-weight: 600; color: var(--ink); cursor: pointer;
    background: var(--surface); border: 1px solid var(--control-border); border-radius: var(--r-pill); padding: 3px 11px; }
  .schip:hover { border-color: var(--axis); background: var(--surface-2); }
  .schip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .schip .lbl { color: var(--muted); font-weight: 400; font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .s-out .schip { background: var(--good-soft); border-color: transparent; }
  #oquad svg { display: block; width: 100%; max-width: 470px; height: auto; }
  .quad .dot { cursor: pointer; }
  .quad .dot:hover :is(circle, path) { stroke: var(--ink); stroke-width: 1.5; }
  .mtab td.stcell { overflow: visible; text-overflow: clip; text-align: left; }
  .mtab td.dim { color: var(--ink-2); }
  .mtab td.bad { color: var(--bad); font-weight: 600; }
  .mtab td.mn .ab { color: var(--muted); font-weight: 400; font-size: var(--fs-small); margin-left: 6px; }
  .movers .mhead { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2) var(--sp-4); margin-bottom: var(--sp-1); }
  .movers .mhead h2 { margin: 0; }
  .movers .mhead .mterm { display: inline-flex; align-items: center; gap: var(--sp-2); color: var(--muted); font-size: var(--fs-small); margin-left: auto; }
  .movers .psub { color: var(--ink-2); font-size: 14px; line-height: 1.5; margin-bottom: var(--sp-4); max-width: var(--read); }
  /* phone: wide tables scroll inside their box; the health table's state names stay put while it scrolls */
  @media (max-width: 700px) {
    .movers .mtab.tqtab { min-width: 860px; }
    .movers .mtab.surge { min-width: 780px; }
    .mtab.score th:first-child, .mtab.score td.mn {
      position: sticky; left: 0; z-index: 1; background: var(--surface); box-shadow: 1px 0 0 var(--line); }
    .mtab.score tr.mrow:hover td.mn { background: linear-gradient(var(--chip-bg), var(--chip-bg)), var(--surface); }
    .movers .mhead .mterm { margin-left: 0; }
  }
  .mcols { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3) var(--sp-6); margin-top: var(--sp-2); }
  @media (max-width: 900px) { .mcols { grid-template-columns: 1fr; } }

  /* ---- tables ---- */
  table.mtab { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: var(--fs-table); font-variant-numeric: tabular-nums; }
  .mtab th {
    color: var(--ink-2); font-weight: 600; font-size: var(--fs-small); line-height: 1.3; text-align: right; vertical-align: bottom;
    padding: 0 0 var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--border); background: var(--surface);
    text-transform: none; letter-spacing: 0;
  }
  .mtab th.l { text-align: left; padding-left: 0; }
  /* Overview tables: a left-aligned header lines up with its cells */
  :where(.overview, .movers) .mtab th.l:not(:first-child) { padding-left: var(--sp-3); }
  .tqtab td.l { text-align: left; }
  /* sentence case even where a header string was authored in lower case */
  .mtab th::first-letter, #tip table.tt th::first-letter { text-transform: uppercase; }
  .mtab td {
    border-top: 1px solid var(--line); padding: 9px 0 9px var(--sp-3); text-align: right;
    color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .mtab td.rk { color: var(--muted); font-size: var(--fs-small); text-align: left; padding-left: 0; }
  .mtab td.mn { text-align: left; font-weight: 600; padding-left: 0; }
  .mtab td.ab { color: var(--muted); font-size: var(--fs-small); text-align: left; }
  .mtab td.kw { text-align: left; color: var(--ink-2); }
  .mtab tr.mrow { cursor: pointer; }
  .mtab tr.mrow:hover td { background: var(--chip-bg); }
  .mtab tr.mrow:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .mtab .up { color: var(--good); font-weight: 600; }
  .mtab .dn { color: var(--bad); font-weight: 600; }
  .mtab .lbl { color: var(--muted); font-weight: 400; }
  .mtab .pill { font-size: 12px; padding: 1px 8px; }
  .mtab .pill.st-low { padding: 0 7px; }
  .mtab tr.sub td { border-top: 0; padding-top: 2px; padding-bottom: 2px; font-size: var(--fs-small); color: var(--ink-2); }
  .mtab button.more { font: inherit; font-size: 14px; font-weight: 500; color: var(--accent); background: none; border: 0;
    padding: 2px 6px; margin-left: -6px; border-radius: var(--r-sm); cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
  .mtab button.more::after { content: ""; width: 6px; height: 6px; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor;
    transform: rotate(-45deg); margin-bottom: 1px; }
  .mtab button.more[aria-expanded="true"]::after { transform: rotate(45deg); margin-bottom: 4px; }
  .mtab button.more:hover { color: var(--accent-strong); background: var(--accent-soft); }
  .mtab button.more:focus-visible { outline: 2px solid var(--accent); outline-offset: 0; }
  .mtab td .trend { font-size: var(--fs-small); margin-left: 4px; }
  .tqtab td.stcell { white-space: normal; text-align: left; }
  .mtab tr.sub td.subwrap { padding: var(--sp-1) 0 var(--sp-4) var(--sp-5); white-space: normal; overflow: visible; }
  table.qtab { width: 100%; border-collapse: collapse; }
  .mtab tr.sub .qtab th { padding: 6px 0 4px var(--sp-3); font-size: 12.5px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  .mtab tr.sub .qtab th.l { padding-left: 0; }
  .mtab tr.sub .qtab td { padding: 5px 0 5px var(--sp-3); border-top: 0; border-bottom: 1px solid var(--line); font-size: var(--fs-small);
    white-space: nowrap; overflow: visible; color: var(--ink-2); }
  .mtab tr.sub .qtab td.l { padding-left: 0; text-align: left; white-space: normal; color: var(--ink); }
  .mtab tr.sub .qtab td.xv { color: var(--ink); font-weight: 600; }
  .qmore { font-size: var(--fs-small); color: var(--muted); padding-top: 6px; }
  .mtab.tqtab th:last-child, .tqtab td.stcell { padding-left: 22px; }
  .mtab.surge { min-width: 640px; }
  .mtab.surge th, .mtab.surge td.mn { white-space: normal; line-height: 1.3; }
  .mtab.surge .nw { white-space: nowrap; }
  .mtab.surge th:last-child, .mtab.surge td.stcell { padding-left: 22px; text-align: left; }
  #msurge, #tqlist { margin-top: var(--sp-2); }
  /* key numbers that are neither good nor bad news (a search surge, clicks we could gain): ink, not a status color */
  .mtab td.xv { color: var(--ink); font-weight: 600; }
  /* plain data tables (chart "show the numbers" views) */
  table { border-collapse: collapse; width: 100%; font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  th, td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th { position: sticky; top: 0; background: var(--surface); color: var(--ink-2); font-weight: 600; }
  th:first-child, td:first-child { text-align: left; }

  /* ---- state cards (one per state) ---- */
  .grid { display: grid; grid-template-columns: 1fr; gap: var(--sp-5); }
  .mapcard .mtitle { font-size: var(--fs-h3); font-weight: 600; margin: 0 0 2px; }
  .mapcard .msub { color: var(--muted); font-size: var(--fs-small); margin-bottom: var(--sp-2); }
  .mapcard .mapbox { display: flex; flex-wrap: wrap; gap: var(--sp-4); align-items: flex-start; }
  .mapcard .mapbox > svg { max-width: 460px; width: 100%; height: auto; flex: 1 1 300px; }
  .mapcard svg path.under { fill: var(--grid); pointer-events: none; }
  .mapcard svg g.fmk { pointer-events: all; cursor: pointer; }
  .mapcard svg path.dma { cursor: pointer; stroke: var(--surface); stroke-width: 0.8; }
  .mapcard svg path.dma:hover { stroke: var(--ink); stroke-width: 1.4; }
  .mapcard svg path.outline { fill: none; stroke: var(--muted); stroke-width: 1.4; pointer-events: none; }
  .maplegend { display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-small); color: var(--ink-2); min-width: 150px; }
  .maplegend .li { display: flex; align-items: center; gap: var(--sp-2); }
  .maplegend .li svg { width: 22px; height: 12px; flex: none; }
  .maplegend .swb { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  /* card header: the state's name (a section title), its status, and the area picker */
  .card .chead { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2) var(--sp-3); }
  .card .chead h2 { font-family: var(--font-ui); font-size: 17px; font-weight: 650; letter-spacing: 0;
    line-height: 1.3; margin: 0; color: var(--ink); display: flex; align-items: baseline; gap: var(--sp-2); }
  .card .chead h2 .ab { font-family: var(--font-ui); color: var(--muted); font-size: var(--fs-small); font-weight: 500; letter-spacing: 0; }
  .card .chead .cpill:empty { display: none; }
  .card .chead .notraffic { color: var(--muted); font-size: 12.5px; font-weight: 500; border: 1px solid var(--line);
    border-radius: var(--r-pill); padding: 1px 10px; }
  .card .chead .msel { margin-left: auto; }
  /* key numbers: label over value, no boxes */
  .stats { display: flex; flex-wrap: wrap; align-items: flex-start; gap: var(--sp-3) var(--sp-6); margin: var(--sp-4) 0 var(--sp-2);
    color: var(--ink-2); font-size: 14px; }
  .stats .modestats { display: contents; }
  .kpi { min-width: 0; }
  .kpi .k { color: var(--muted); font-size: var(--fs-small); line-height: 1.3; }
  .kpi .v { color: var(--ink); font-size: 17px; font-weight: 600; line-height: 1.4; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .kpi .v .up, .kpi .v .dn, .kpi .v .lbl { font-size: var(--fs-small); margin-left: 4px; }
  .kpi .v .na { color: var(--ink-2); font-size: 15px; font-weight: 500; }
  .kpi .s { color: var(--muted); font-size: var(--fs-small); line-height: 1.35; }
  .kpi .s b { color: var(--ink-2); font-weight: 600; font-variant-numeric: tabular-nums; }
  .stats .lbl { color: var(--muted); font-weight: 400; }
  .stats .pages { cursor: help; }
  .stats .pages .v span.u { text-decoration: underline dotted var(--axis); text-underline-offset: 4px; }
  .stats .up { color: var(--good); font-weight: 600; }
  .stats .dn { color: var(--bad); font-weight: 600; }
  .chart { position: relative; margin-top: var(--sp-3); }
  .chart svg { display: block; width: 100%; height: auto; }
  details.tbl { margin: var(--sp-2) 0 0; }
  .tblwrap th .lbl { color: var(--muted); font-weight: 400; }
  .tblwrap { max-height: 300px; overflow: auto; border: 1px solid var(--border); border-radius: var(--r-md); margin-top: var(--sp-2); }
  @media (max-width: 600px) {
    .stats { gap: var(--sp-3) var(--sp-5); }
    .kpi { flex: 1 1 40%; }
    .card .chead .msel { margin-left: 0; flex: 1 1 100%; }
  }

  /* ---- hover readout ---- */
  #tip {
    position: fixed; pointer-events: none; z-index: 20; display: none;
    background: var(--tooltip-bg); border: 1px solid var(--border); border-radius: var(--r-md);
    box-shadow: var(--shadow-pop); color: var(--ink);
    padding: 10px 12px; font-size: var(--fs-small); line-height: 1.45; min-width: 200px; max-width: 420px;
  }
  #tip .d { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
  #tip .d .pill { font-size: 12px; padding: 0 8px; margin-left: 6px; vertical-align: 1px; }
  #tip .tnote { color: var(--muted); font-size: 12.5px; margin-top: var(--sp-1); }
  #tip .d .lbl { color: var(--muted); font-weight: 400; margin-left: 8px; }
  #tip .row { display: flex; align-items: center; gap: var(--sp-2); justify-content: space-between; color: var(--ink-2); padding: 2px 0; }
  #tip .row .v { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
  #tip .row .n { display: inline-flex; align-items: center; gap: 6px; max-width: 300px; overflow-wrap: anywhere; }
  #tip table.tt { border-collapse: collapse; width: 100%; font-size: var(--fs-small); }
  #tip table.tt th {
    position: static; background: none; color: var(--muted); font-weight: 600; font-size: 12px; text-align: right;
    padding: 0 0 4px 14px; border-bottom: 1px solid var(--line); text-transform: none; letter-spacing: 0;
  }
  #tip table.tt th:first-child { text-align: left; padding-left: 0; }
  #tip table.tt td {
    padding: 3px 0 3px 14px; text-align: right; white-space: nowrap; border-bottom: 0;
    font-variant-numeric: tabular-nums; color: var(--ink); font-size: var(--fs-small);
  }
  #tip table.tt td.n { text-align: left; padding-left: 0; color: var(--ink-2); font-variant-numeric: normal; }
  #tip table.tt td.n span.sw { display: inline-flex; vertical-align: -1px; margin-right: 6px; }
  #tip table.tt td:not(.n) { font-weight: 600; }
  #tip table.tt .pos { color: var(--good); }
  #tip table.tt .zero { color: var(--muted); font-weight: 400; }

  footer.notes { margin-top: var(--sp-7); padding-top: var(--sp-3); border-top: 1px solid var(--border); }
  footer.notes details.about { margin-top: 0; }
  footer.notes .about-body h4:first-child { margin-top: var(--sp-2); }

  @media (max-width: 600px) {
    :root { --fs-h1: 23px; --fs-h2: 18px; }
    .panel, .overview, .movers, .card { padding: var(--sp-4); border-radius: var(--r-md); }
    nav.tabs button { font-size: 14px; padding: 9px 11px 8px; }
  }
/*__TABS_CSS__*/
</style>

<div class="wrap">
  <div class="topbar" id="topbar">
    <h1>WFE SEO Dashboard</h1>
    <nav class="tabs" id="tabs" role="tablist" aria-label="Dashboard views"></nav>
  </div>

  <div class="tabpane" id="pane-main" role="tabpanel" aria-labelledby="tab-main">
  <div class="controls" id="controls"></div>
  <section class="overview" id="overview" hidden>
    <h2>SEO health by state</h2>
    <div class="osub" id="osub"></div>
    <div class="ssum" id="ssum"></div>
    <div class="ocols">
      <div class="ocol"><div id="oscore"></div></div>
      <div class="ocol quad">
        <div class="qhead"><h3 id="oqtitle">Compare two measures</h3>
          <label class="qsel">Compare <select id="qpreset" class="sel"></select></label></div>
        <div class="qbody">
          <div id="oquad"></div>
          <div class="qside">
            <p class="qq" id="oqq"></p>
            <ul class="qlegend" id="oqleg"></ul>
            <details class="about"><summary>How to read this chart</summary><div class="about-body" id="oqnote"></div></details>
          </div>
        </div>
      </div>
    </div>
    <details class="about"><summary>How this is calculated</summary><div class="about-body" id="oabout"></div></details>
  </section>
  <section class="movers" id="movers" hidden>
    <div class="mhead">
      <h2>Metros surging now</h2>
      <label class="mterm">Search term <select id="mkw" class="sel"></select></label>
    </div>
    <div class="psub" id="mnote"></div>
    <div id="msurge"></div>
    <details class="about"><summary>How this is calculated</summary><div class="about-body">
      <p>A metro is listed when one of its search terms averaged at least 1.5× last week's level this week, and at least 5
      on the metro's own 0–100 index. Each market is listed once, under its biggest jump. Both weeks come from the most
      recent stretch Google Trends reports consistently.</p>
      <dl class="tags">
        <dt><span class="pill st-out">Capturing</span></dt><dd>Our visitors from that metro this week averaged at least 1.5× last week's.</dd>
        <dt><span class="pill st-miss">Not capturing</span></dt><dd>Searches jumped, but our visitors from there didn't reach 1.5× last week's (or stayed under 1 a day).</dd>
      </dl>
      <p>Click a row to open that metro's chart. Hover it for the term's exact values.</p>
    </div></details>
  </section>
  <section class="movers" id="tq" hidden>
    <div class="mhead">
      <h2>Top search opportunities</h2>
    </div>
    <div class="psub" id="tqnote"></div>
    <div id="tqlist"></div>
    <details class="about"><summary>How this is calculated</summary><div class="about-body">
      <p>One row per page on our site (usually one fire), ranked by <b>extra clicks per week</b>. That is the clicks its
      queries would get at the click-through rate this site normally earns at their position, minus the clicks they
      actually got.</p>
      <h4>Reasons</h4>
      <dl class="tags">
        <dt><span class="pill st-miss">Page 2+</span></dt><dd>Most of the gap is queries ranking below the first page.</dd>
        <dt><span class="pill st-low">Weak snippet</span></dt><dd>We rank on page 1 but get fewer clicks than usual for that position.</dd>
        <dt><span class="pill st-track">New demand</span></dt><dd>The page had no impressions two weeks earlier.</dd>
        <dt><span class="pill st-low">Old page</span></dt><dd>Traffic landing on a fire more than 90 days old.</dd>
      </dl>
      <h4>The query list</h4>
      <p>Click a page's query count to see its biggest queries. Expected clicks = impressions × the click rate this site
      usually gets at that position; queries below page 1 are counted at position 5. Extra clicks per week = (expected −
      actual clicks) ÷ 2. Click a row to open the state.</p>
    </div></details>
  </section>
  <div class="sechead" id="ghead">
    <h2>State by state</h2>
    <div class="psub">Search demand, Google visibility and our traffic in each state over the chosen dates. Pick a metro on a card to zoom in.</div>
    <details class="about"><summary>How to read these charts</summary><div class="about-body" id="howto"></div></details>
  </div>
  <div class="sgroup">
    <div class="lgbar" id="lgbar" role="group" aria-label="Chart lines and options"></div>
    <div class="grid" id="grid"></div>
  </div>

  <footer class="notes">
    <details class="about"><summary>Methodology and data sources</summary><div class="about-body">
    <h4>Site traffic and search demand</h4>
    <p>Site traffic is pulled from the PostHog API each time the dashboard is built. State and metro totals are true
    daily uniques: a person visiting several of a state's pages in one day counts once. The per-page list (hover the
    organic visits number on a card) counts a person once per page visited, so pages can sum to more than the total.</p>
    <p>Search demand is Google Trends daily interest, measured <b>in-state</b> (queries made from within the state itself,
    geo US-XX) or per metro. Keywords: wildfire {state}, fire {state}, fire {abbr}, "fire near me", and in metro view
    "fire near {city}" (the metro's biggest city). Each area's keywords come from one Google Trends request, so they share
    one scale (the area's best term-day = 100). They are directly comparable within an area, but not across areas. When
    Google Trends returns zeros for many metros on the same day (unprocessed recent days), those metro-days are treated as
    missing rather than as zero.</p>

    <h4>SEO health (the overview and card headers)</h4>
    <p>Everything that judges health uses the dates picked with the date button at the top, less the latest day, which is
    still partial. For example, "Last 14 days" judges the 13 complete days in it.</p>
    <dl>
      <dt>Search</dt><dd>The average of an area's keyword indices over those days, as a multiple of its average over the
      same number of days immediately before (1× = no change). "All data" has no earlier period, so it can't be judged.</dd>
      <dt>Visits</dt><dd>In the table and on the cards ("Search → visits"): the same for our organic visits, i.e. visitors arriving
      from a search engine (Google, Bing, DuckDuckGo, Yahoo, Ecosia, Brave), counted by PostHog. They track Search Console
      clicks within a few percent. "Clicks" on this page always means Google Search Console clicks.</dd>
      <dt>Status</dt><dd>Visits ÷ search, whether search rose or fell. Below 0.6× = missing demand (our traffic fell behind
      search), above 1.25× = outperforming, otherwise tracking.</dd>
      <dt>Missed visits per week (estimate)</dt><dd>(search multiple − our multiple) × our average day in the previous period × 7.</dd>
      <dt>What Search Console shows</dt><dd>This dashboard's own labels (Google doesn't supply them), read from Search
      Console over the same dates, up to its last complete day. Search Console runs about two days behind. Every multiple
      compares with the previous period. For states missing demand:
      <ul>
        <li><b>Losing visibility</b>: our impressions fell well behind search (impressions ÷ search below 0.6). Points to
        a ranking or indexing gap.</li>
        <li><b>Shown, not clicked</b>: our clicks fell well behind our impressions (clicks ÷ impressions below 0.6). Points
        to a title, snippet or position gap.</li>
        <li><b>Google clicks kept pace</b>: our Google clicks rose with searching, so the shortfall is in other search
        engines or in tracking.</li>
        <li><b>Visibility and clicks both slipped</b>: none of the above.</li>
      </ul></dd>
      <dt>Can't judge yet</dt><dd>Google Trends reports low-volume days as zero except for the most recent ~14 days of each
      request. For states whose search history is mostly zero there is no reliable level to compare, so they are left out
      of the health table.</dd>
    </dl>
    <p>Short windows react fastest but flip on noise. 14 days halves how often a status flips compared with 7, while a
    real surge still registers the day after it starts. Longer windows show the season's overall picture. The card
    headers' Search Console figures compare those dates with the same number of days immediately before them. The comparison
    chart plots any two of these multiples on log axes, capped at 24×. States past the cap are drawn scaled down along
    their own ray, so they stay on the correct side of the diagonal.</p>

    <h4>Chart dates</h4>
    <p>The date button at the top sets the window every state chart shows: the last 7, 14, 30 or 90 days, all data, or
    any start and end day picked on its two calendars. SEO health (the overview and card headers) judges the same dates;
    the surge list and opportunities keep their own fixed windows.</p>
    <p>The left axis rescales to the largest value visible in the chosen dates, but index values don't change when you
    pick dates. Traffic and Search Console impressions stay indexed to their own peak over the whole window, and the
    search terms share one Google Trends scale per area (100 = the busiest term-day). Search Console average position and
    CTR are plotted on the right-hand axis in their own units, sharing the left axis' gridlines. Position is inverted
    (1 = top result at the top). With 7-day smoothing on, average position and CTR are impression-weighted over the
    7 days.</p>
    <p><b>Best position</b> is, for each day, our best average position over the 7 days ending that day, among queries
    that brought the state's pages (or, in a metro view, its city queries) at least 20 impressions in those 7 days. Brand
    queries and likely-automated queries are left out, and the hover names the query. The trailing week keeps the line
    continuous and steady, so it moves only when a ranking holds for days. It can sit below the average line
    when our strongest rankings are all on low-volume queries, and the smoothing toggle doesn't change it. Google
    withholds rare queries, so it only sees the queries Search Console reports.</p>

    <h4>Metro view</h4>
    <p>The dropdown on a state card narrows the chart to one metro area. Fire diamonds narrow too: only fires that started
    inside the metro's counties in that state. Site traffic counts only visitors whose GeoIP location is within 50 miles
    of the metro's biggest city (still viewing that state's pages), and search interest is fetched for the metro's own
    Google Trends market (Nielsen DMA, e.g. geo US-OR-820 for Portland). A state's dropdown lists every DMA Google files
    under that state. Cross-border markets (Denver appears under Nebraska and Wyoming too) use that state's keywords,
    capturing spillover audiences.</p>

    <h4>Search Console</h4>
    <p>Impressions, clicks, CTR and average position come from the Google Search Console API for the
    https://fires.cornea.is/ property (web search; image, video and news are under 1% of web), synced daily on the
    maintainer's machine. The last 7 days are re-fetched every run, so Google's revisions and missed days are picked up.
    State series use page-level totals, which are complete. Google withholds rare queries whenever query text is
    requested (about half of impressions here), so query-based views (metro slices and Top search opportunities) cover
    only the queries Google discloses. CTR is recomputed from summed clicks and impressions; average position is
    impression-weighted (1 = the top result). Data lags about two days.</p>

    <h4>Top search opportunities</h4>
    <p>Queries from the last 14 complete Search Console days, grouped by the page they land on (brand and homepage
    searches excluded). <b>Extra clicks per week</b> (potential clicks) = for each page, the clicks its queries would have
    earned at this site's usual click-through rate for their position (for queries below page 1, at position 5), minus the
    clicks they actually got. Shown per week; pages under 3 a week are left out. The usual click-through rate by position
    is fitted from this site's last 28 days. Queries that drew thousands of impressions but never a single click, where
    real searchers would have produced 10 or more, are treated as automated traffic and excluded. Page impressions and
    their trend are the page's complete Search Console totals.</p>

    <h4>Metros surging now</h4>
    <p>For each metro, the term whose average this week is highest relative to last week, counting only terms averaging at
    least 5 on the metro's own 0–100 index. A metro is shown when this week is 1.5× last week or more (each market listed
    once). Both weeks come from the most recent stretch that Google Trends reports consistently. <b>Capturing</b> = our
    visitors from that metro this week averaged at least 1.5× last week's.</p>

    <h4>Fire milestones</h4>
    <p>Orange diamonds straddling the baseline mark wildfire start dates in that state, sourced from the fire API
    (fire-api-dev.web.app): wildfires only (prescribed burns excluded), &gt;100 acres final size, started within the
    window. A small number above a diamond counts multiple starts that day; hover the chart to see fire names, acreage,
    and nearby population. A diamond's center sits on the fire's start date. Start date = the fire's created-on date
    (UTC).</p>

    <h4>Impactful fires</h4>
    <p>A fire is impactful when at least P people live within R miles of its start point. Both are set with the sliders
    under Settings (default 2k within 5 mi). Distance is measured from the fire's approximate edge: R plus the fire's own
    radius if its final acreage were a circle (√(acres⁄640π) miles, which adds ~7 mi for a 100k-acre fire and ~0 for a
    100-acre fire). Population = 2020 Census block-group centroids (national file, so state borders don't clip counts).
    Solid diamond = impactful at the current thresholds, hollow = not; a day with several fires shows solid if any
    qualifies. Block-group resolution makes counts step-shaped under ~2 miles, so the radius slider starts at 2 mi.</p>

    <h4>Caveats</h4>
    <ul>
      <li>Site traffic is indexed to its own peak. Compare timing and shape against search, not absolute level.</li>
      <li>Abbreviation terms can be ambiguous to Google ("fire or", "fire co", "fire id" catch unrelated queries), which
      inflates their baselines.</li>
      <li>A keyword line flat at zero means search volume stayed below Google's reporting threshold all window. That is not
      missing data (state-restricted volumes are smaller, so this happens more often in in-state mode).</li>
      <li>The final day of the window is partial in Google's data.</li>
    </ul>
    </div></details>
  </footer>
  </div>
  <div class="tabpane" id="pane-states" role="tabpanel" aria-labelledby="tab-states" hidden></div>
  <div class="tabpane" id="pane-hpage" role="tabpanel" aria-labelledby="tab-hpage" hidden></div>
  <div class="tabpane" id="pane-hall" role="tabpanel" aria-labelledby="tab-hall" hidden></div>
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
const visible = { traffic: true, k0: false, k1: false, k2: false, k3: false, k4: false, fires: true, gi: true, gpos: true, gbest: true, gctr: true };
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
/* fires.json also carries active fires under 100ac (new starts are unsized at 0ac);
   charts and counts keep the historical >100ac cut, only map markers show them all */
const chartFires = st => (st.fires || []).filter(f => (f.a || 0) > 100);
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
/* a legend entry that shows or hides its line(s) on every state chart */
function chip(k, sw, label, title) {
  const on = k.split(",").every(x => visible[x]);
  return `<button type="button" class="lgt${on ? "" : " off"}" data-k="${k}" aria-pressed="${on}"${title ? ` title="${title}"` : ""}>${sw}<span>${label}</span></button>`;
}
function buildControls() {
  const c = document.getElementById("controls");
  const both = `<svg width="22" height="12" aria-hidden="true"><line x1="1" y1="3.5" x2="21" y2="3.5" stroke="var(--f)" stroke-width="2"/><line x1="1" y1="8.5" x2="21" y2="8.5" stroke="var(--f)" stroke-width="2" stroke-dasharray="4 3"/></svg>`;
  const chev = `<span class="chev" aria-hidden="true"></span>`;
  let html = `<select class="statef sel" id="statef" aria-label="Show one state"><option value="-1">All states</option>` +
    DATA.states.map(st => `<option value="${st.key}">${st.name}</option>`).join("") + `</select>`;
  html += `<details class="pop dpick" id="dpick"><summary class="lg dbtn" title="Dates every state chart shows, also used to judge SEO health">
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="1.5" y="2.5" width="11" height="10" rx="1.5"/><line x1="1.5" y1="5.6" x2="12.5" y2="5.6"/><line x1="4.5" y1="1" x2="4.5" y2="3.8"/><line x1="9.5" y1="1" x2="9.5" y2="3.8"/></svg>
      <span id="dlabel"></span>${chev}</summary>
    <div class="popbody dpbody">
      <div class="dpresets" role="group" aria-label="Date presets">` +
      RANGE_PRESETS.map(([k, l]) => `<button type="button" data-p="${k}" aria-pressed="false">${l}</button>`).join("") + `</div>
      <div class="dcals"><div class="dcal" id="dcal-start"></div><div class="dcal" id="dcal-end"></div></div>
    </div></details>`;
  c.innerHTML = html;

  /* chart-only controls live with the charts: series toggles, search terms, smoothing, fire settings */
  const lgb = document.getElementById("lgbar");
  html = `<span class="lgkey">Show on charts</span>`;
  html += chip("traffic", legendSwatch("traffic"), "Our traffic");
  html += chip("fires", legendSwatch("fires"), "Fire starts");
  if (GSC) {
    html += `<span class="lgroup">Search Console</span>`;
    html += chip("gi", legendSwatch({ color: "var(--gi)" }), "Impressions", "How often Google showed our pages.");
    html += chip("gpos", legendSwatch({ color: "var(--gp)", dash: "0.1 3.6", cap: true }), "Avg position",
      "Right-hand axis. Average position over all our impressions (1 = top result).");
    html += chip("gbest", legendSwatch({ color: "var(--gp)", dash: "5 3" }), "Best position",
      `Right-hand axis. Our best average position over the ${GSC.bestDays} days ending each day, among queries with at least ${GSC.bestMin} impressions in those days (brand and likely-automated queries left out). Hover a day for the query.`);
    html += chip("gctr", legendSwatch({ color: "var(--gc)" }), "CTR", "Right-hand axis. Clicks ÷ impressions.");
  }
  html += `<details class="pop lgmore"><summary class="lg">Search terms${chev}</summary><div class="popbody">
      <div class="lghead">Google Trends search interest, measured within each state.</div>
      ${chip("k1,k2", both, `Fire <span class="lbl">{state / abbr}</span>`)}
      ${chip("k0", legendSwatch(KW_META[0]), `Wildfire <span class="lbl">{state}</span>`)}
      ${chip("k3", legendSwatch(KW_META[3]), "Fire near me")}
      ${chip("k4", legendSwatch(KW_META[4]), `Fire near <span class="lbl">{city}, metro view</span>`)}
    </div></details>`;
  html += `<span class="gap"></span>`;
  html += `<label class="smooth"><input type="checkbox" id="sm"> 7-day smoothing</label>`;
  html += `<details class="pop pop-r"><summary class="lg">Settings${chev}</summary><div class="popbody">
      <div class="ptitle">${legendSwatch("fires")} Impactful fires</div>
      <div class="pnote">A fire counts as impactful when at least this many people (2020 Census) live within this distance of it, measured from its approximate edge.</div>
      <div class="prow"><span class="plab">At least</span>
        <input type="range" id="ipop" min="0" max="${POP_STEPS.length - 1}" step="1" value="${POP_STEPS.indexOf(impact.pop)}" aria-label="Impactful population threshold">
        <b id="ipopv">2k</b><span>people</span></div>
      <div class="prow"><span class="plab">Within</span>
        <input type="range" id="irad" min="0" max="${RING_STEPS.length - 1}" step="1" value="${RING_STEPS.indexOf(impact.ring)}" aria-label="Impactful radius">
        <b id="iradv">5 mi</b></div>
    </div></details>`;
  lgb.innerHTML = html;

  const sw = legendSwatch;
  document.getElementById("howto").innerHTML = `
    <p>Every line is indexed so shapes line up: 100 = that line's peak in the window. The date button at the top sets the
    window every chart shows. The bar above the cards turns each line on or off.</p>
    <dl class="key">
      <dt>${sw("traffic")} Our traffic</dt><dd>Visitors to the state's pages, in green with a shaded area.</dd>
      <dt>${sw("fires")} Fire starts</dt><dd>Orange diamonds on the baseline. Solid = impactful under the current Settings,
        hollow ${sw("fires_h")} = not.</dd>` +
      (GSC ? `
      <dt>${sw({ color: "var(--gi)" })} Impressions</dt><dd>How often Google showed our pages (Search Console), in blue,
        indexed the same way.</dd>
      <dt>${sw({ color: "var(--gp)", dash: "0.1 3.6", cap: true })} Avg position</dt><dd>Grey dotted line on the right-hand
        axis, in its own units. Position is inverted so 1, the top result, sits at the top.</dd>
      <dt>${sw({ color: "var(--gp)", dash: "5 3" })} Best position</dt><dd>Grey dashed: our best average position over the
        ${GSC.bestDays} days ending that day, among queries with at least ${GSC.bestMin} impressions in those days. Hover a
        day to see the query.</dd>
      <dt>${sw({ color: "var(--gc)" })} CTR</dt><dd>Clicks ÷ impressions, in berry, on the right-hand axis.</dd>` : "") + `
      <dt>${both} Search terms</dt><dd>In-state Google Trends: searches made from within the state. Turn them on under
        Search terms. "Fire {state / abbr}" draws the state name solid and the two-letter abbreviation dashed.</dd>
    </dl>
    <p>Pick a metro on a card for metro-level data. In a metro view, Search Console covers queries that mention the metro's
    biggest city. Search Console runs about two days behind. Full definitions are under Methodology and data sources at
    the bottom of the page.</p>`;
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
  const setCtrlH = () => {
    const st = getComputedStyle(c).position === "sticky";
    /* heights rounded DOWN: a bar pinned under another may tuck a fraction of a pixel beneath it, but never leaves a
       sliver of scrolled content showing between them (offsetHeight rounds 60.5 up to 61) */
    const hOf = el => Math.floor(el.getBoundingClientRect().height);
    document.documentElement.style.setProperty("--top-h", hOf(document.getElementById("topbar")) + "px");
    document.documentElement.style.setProperty("--ctrl-h", (st ? hOf(c) : 0) + "px");
    document.documentElement.style.setProperty("--lg-h", (getComputedStyle(lgb).position === "sticky" ? hOf(lgb) : 0) + "px");
  };
  if (window.ResizeObserver) { const ro = new ResizeObserver(setCtrlH); ro.observe(c); ro.observe(lgb); ro.observe(document.getElementById("topbar")); }
  setCtrlH();
  document.getElementById("statef").addEventListener("change", e => {
    stateFilter = e.target.value;
    applyStateFilter();
  });
  lgb.querySelectorAll(".lgt[data-k]").forEach(btn => btn.addEventListener("click", () => {
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
    document.getElementById("dlabel").innerHTML = pl ? `${pl} <span class="lbl">${rangeText()}</span>` : rangeText();
    dpick.querySelectorAll("[data-p]").forEach(b => {
      const on = b.dataset.p === range.preset;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    if (resetViews || !calView.start) { calView.start = monthOf(DATA.dates[range.r0]); calView.end = monthOf(DATA.dates[range.r1]); }
    renderCal("start"); renderCal("end");
    try { localStorage.setItem("wdo-overview-range", JSON.stringify(range.preset === "custom"
      ? { p: "custom", from: DATA.dates[range.r0], to: DATA.dates[range.r1] } : { p: range.preset })); } catch (e) {}
  };
  /* first index on or after a YYYY-MM-DD date */
  const idxAt = d => { const i = DATA.dates.findIndex(x => x >= d); return i < 0 ? N - 1 : i; };
  try {
    const saved = JSON.parse(localStorage.getItem("wdo-overview-range") || "null");
    if (saved && saved.p === "custom" && saved.from && saved.to) {
      const [a, b] = saved.from <= saved.to ? [saved.from, saved.to] : [saved.to, saved.from];
      if (b >= D0 && a <= D1) setRange("custom", idxAt(a), idxAt(b));   /* ignore a range the data has moved past */
    } else if (saved && RANGE_PRESETS.some(([k]) => k === saved.p)) setRange(saved.p);
  } catch (e) {}
  syncRange();
  dpick.querySelector(".dpbody").addEventListener("click", e => {
    const pr = e.target.closest("[data-p]"), nav = e.target.closest(".dnav"), day = e.target.closest(".dday");
    if (pr) { setRange(pr.dataset.p); syncRange(); rangeChanged(); dpick.open = false; return; }
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
      syncRange(false); rangeChanged();
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
const ML = 40, MT = 24, MB = 24, RAX = 46;   /* RAX = width of each right-hand axis column */
const DIDX = {};
DATA.dates.forEach((d, i) => DIDX[d] = i);
/* last complete Search Console day on the dashboard axis */
const GSC_LAST = !GSC ? null
  : DIDX[GSC.lastComplete] !== undefined ? DIDX[GSC.lastComplete]
  : GSC.lastComplete > DATA.dates[N - 1] ? N - 1 : null;
/* which metro a fire is in: its start point, projected like the metro map's fire markers, tested
   against each metro's outline on that map (the DMA's counties clipped to the state; even-odd rule) */
function metroOfFire(st, f) {
  if (f._mk !== undefined) return f._mk;
  f._mk = null;
  const map = DATA.maps && DATA.maps[st.key];
  if (!map || f.lat === undefined) return null;
  if (!map._rings) map._rings = Object.entries(map.metros).map(([k, d]) =>
    [k, d.split("Z").filter(Boolean).map(r => r.replace(/^M/, "").split("L").map(pt => pt.split(" ").map(Number)))]);
  const x = (f.lon - map.proj.minx) * map.proj.kx, y = (map.proj.maxy - f.lat) * map.proj.ky;
  for (const [k, rings] of map._rings) {
    let inside = false;
    for (const ring of rings)
      for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) {
        const [xa, ya] = ring[a], [xb, yb] = ring[b];
        if ((ya > y) !== (yb > y) && x < (xb - xa) * (y - ya) / (yb - ya) + xa) inside = !inside;
      }
    if (inside) { f._mk = k; break; }
  }
  return f._mk;
}
/* fires for a card's view: the whole state, or in a metro view only fires inside that metro */
function viewFires(st, sel) {
  const all = chartFires(st);
  return sel ? all.filter(f => metroOfFire(st, f) === sel.key) : all;
}
function fireMap(st, sel) {
  const key = sel ? sel.key : "*";
  st._fmap = st._fmap || {};
  if (!st._fmap[key]) {
    const m = st._fmap[key] = {};
    viewFires(st, sel).forEach(f => {
      const i = DIDX[f.d];
      if (i !== undefined) (m[i] = m[i] || []).push(f);
    });
  }
  return st._fmap[key];
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
setRange("14");
const rangeText = () => `${fdate(DATA.dates[range.r0])} – ${fdate(DATA.dates[range.r1])}`;

/* right-hand axes: Search Console avg position and CTR in their own units */
const rightAxes = () => !GSC ? [] : [visible.gpos || visible.gbest ? "gpos" : null, visible.gctr ? "gctr" : null].filter(Boolean);
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
const RLINE = {
  avg: `stroke="var(--gp)" stroke-width="2" stroke-dasharray="0.1 3.6" stroke-linecap="round"`,
  best: `stroke="var(--gp)" stroke-width="1.5" stroke-dasharray="5 3"`,
  ctr: `stroke="var(--gc)" stroke-width="1.75" stroke-linecap="round"`,
};
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
  const ui = `font-family="Figtree, system-ui, sans-serif"`;

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
    const lines = !gs ? [] : k === "gctr" ? [["ctr", gscRatio(gs, "ctr")]]
      : [visible.gpos && ["avg", gscRatio(gs, "pos")], visible.gbest && gs.b && ["best", gs.b]   /* already a trailing 7-day measure: not smoothed again */].filter(Boolean);
    const vals = lines.flatMap(([, s]) => s.slice(r0, r1 + 1).filter(v => v != null));
    const ax = { k, lines, x: w - mr + 8 + ai * RAX, has: vals.length > 0 };
    if (k === "gpos") {      /* inverted: 1 = top result at the top */
      const hi = vals.length ? Math.max(...vals) : 1;
      ax.step = stepUp(Math.max(0, hi - 1) / nGrid, [1, 2, 3, 4, 5, 10, 15, 20, 25, 50, 100]);
      ax.Y = v => MT + (v - 1) / (ax.step * nGrid) * ih;
      ax.tick = kk => String(1 + kk * ax.step);
      ax.color = "var(--gp)"; ax.title = "Position";
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
  g += `<text x="${ML - 6}" y="${MT - 10}" text-anchor="end" font-size="11" font-weight="600" fill="var(--muted)" ${ui}>Index</text>`;
  for (let k = 0; k <= nGrid; k++) {
    const v = k * step, y = Y(v).toFixed(1);
    g += `<line x1="${ML}" y1="${y}" x2="${w - mr}" y2="${y}" stroke="${v === 0 ? "var(--axis)" : "var(--grid)"}" stroke-width="1"/>`;
    if (v > 0) g += `<text x="${ML - 6}" y="${(+y + 3.5).toFixed(1)}" text-anchor="end" font-size="11.5" fill="var(--muted)" ${ui}>${+v.toFixed(3)}</text>`;
  }
  rAxes.forEach(ax => {
    g += `<text x="${ax.x}" y="${MT - 10}" font-size="11" font-weight="600" fill="var(--muted)" ${ui}>${ax.title}</text>`;
    if (!ax.has) { g += `<text x="${ax.x}" y="${MT + 12}" font-size="11.5" fill="var(--muted)" ${ui}>–</text>`; return; }
    for (let k = 0; k <= nGrid; k++) {
      const y = (ax.k === "gpos" ? ax.Y(1 + k * ax.step) : ax.Y(k * ax.step));
      g += `<text x="${ax.x}" y="${(y + 3.5).toFixed(1)}" font-size="11.5" fill="var(--muted)" ${ui}>${ax.tick(k)}</text>`;
    }
  });
  let lastR = -1e9;
  xTicks(r0, r1, iw).forEach(([i, t, anchor]) => {
    const tw = t.length * 6.6;          /* Figtree 11.5px, generous */
    let x = Xr(i);
    if (anchor === "middle") x = Math.min(w - mr - tw / 2 + 4, Math.max(ML + tw / 2 - 4, x));
    const left = anchor === "start" ? x : x - tw / 2;
    if (left < lastR + 6) return;       /* never let two labels touch */
    lastR = left + tw;
    g += `<text x="${x.toFixed(1)}" y="${h - 6}" text-anchor="${anchor}" font-size="11.5" fill="var(--muted)" ${ui}>${t}</text>`;
  });

  let peak = "";
  if (visible.traffic && hasTraffic) {
    const s = disp(trafIdx), p = pathOf(s, Y);
    g += `<path d="${p} L ${Xr(r1).toFixed(1)} ${Y(0).toFixed(1)} L ${ML} ${Y(0).toFixed(1)} Z" fill="var(--traffic-fill)" stroke="none"/>`;
    g += `<path d="${p}" fill="none" stroke="var(--traffic)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    /* selective direct label: traffic peak within the visible range */
    let pi = r0;
    for (let i = r0; i <= r1; i++) if (traf[i] > traf[pi]) pi = i;
    const px = Xr(pi), py = Y(s[pi]);
    let lx = px, ly = py - 6, anchor = px > w - mr - 90 ? "end" : px < ML + 70 ? "start" : "middle";
    if (ly < MT - 2) {                   /* no room above: put it beside the dot */
      ly = py + 3.5;
      if (px > w - mr - 120) { anchor = "end"; lx = px - 6; } else { anchor = "start"; lx = px + 6; }
    }
    /* drawn last (below), so no other line crosses the label */
    peak = `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="4" fill="var(--traffic)" stroke="var(--surface)" stroke-width="2"/>`;
    peak += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${anchor}" class="pk" font-size="11.5" font-weight="600" fill="var(--ink-2)" ${ui}>Peak ${fmt(traf[pi])} users</text>`;
  }
  if (k25) k25.forEach((s0, i) => {
    if (!visible["k"+i] || !s0.length) return;
    const m = KW_META[i];
    g += `<path d="${pathOf(disp(s0), Y)}" fill="none" stroke="${m.color}" stroke-width="1.25"${m.dash ? ` stroke-dasharray="${m.dash}"` : ""} stroke-linejoin="round" opacity="0.35"/>`;
  });
  if (kwS) kwS.forEach((s0, i) => {
    if (!visible["k"+i] || !s0.length) return;
    const m = KW_META[i];
    g += `<path d="${pathOf(dispN(s0), Y)}" fill="none" stroke="${m.color}" stroke-width="1.75"${m.dash ? ` stroke-dasharray="${m.dash}"` : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
  });
  gLines.forEach(([, s, col]) => {
    const d = pathOf(s, Y);
    if (d) g += `<path d="${d}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  });
  rAxes.forEach(ax => {
    if (!ax.has) return;
    ax.lines.forEach(([kind, series]) => {
      /* a day with no neighbours has no line segment: draw it as a dot */
      for (let i = r0; i <= r1; i++)
        if (series[i] != null && (i === r0 || series[i - 1] == null) && (i === r1 || series[i + 1] == null))
          g += `<circle cx="${Xr(i).toFixed(1)}" cy="${ax.Y(series[i]).toFixed(1)}" r="1.8" fill="${ax.color}"/>`;
      g += `<path d="${pathOf(series, ax.Y)}" fill="none" ${RLINE[kind]} stroke-linejoin="round"/>`;
    });
  });

  if (visible.fires) {
    const fm = fireMap(st, sel), y0 = Y(0);
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
        g += `<path d="M ${x.toFixed(1)} ${(y0-4).toFixed(1)} L ${(x+3.1).toFixed(1)} ${y0.toFixed(1)} L ${x.toFixed(1)} ${(y0+4).toFixed(1)} L ${(x-3.1).toFixed(1)} ${y0.toFixed(1)} Z" fill="none" stroke="var(--fire-mk)" stroke-width="1.4"/>`;
      if (n > 1 && x - lastCount >= 11) {
        g += `<text x="${x.toFixed(1)}" y="${(y0-7).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="600" fill="var(--ink-2)" ${ui}>${n}</text>`;
        lastCount = x;
      }
    }
  }
  g += peak;
  g += `<line class="xh" x1="-10" y1="${MT}" x2="-10" y2="${MT + ih}" stroke="var(--ink-2)" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>`;
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" data-w="${w}" data-mr="${mr}" role="img" aria-label="Search interest (${viewOf(st, sel).label}) vs site traffic for ${st.name}, ${rangeText()}">${g}</svg>`;
}

/* ---------- health math shared by cards + overview (one clock: the picked chart dates) ---------- */
/* Top search opportunities' fixed Search Console window (gsc_sync's top_window) */
const WIN = 14;
/* the health window: the dates picked at the top, less today's still-partial day.
   Its Search Console side stops at GSC's last complete day (g = null when that's before the start). */
function healthWin() {
  const b = Math.min(range.r1, N - 2), a = Math.min(range.r0, b);
  const gb = GSC_LAST == null ? null : Math.min(b, GSC_LAST);
  return { a, b, n: b - a + 1, g: gb != null && gb >= a ? { b: gb, n: gb - a + 1 } : null };
}
const spanText = (a, b) => a === b ? fdate(DATA.dates[a]) : `${fdate(DATA.dates[a])} – ${fdate(DATA.dates[b])}`;
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
/* the baseline a health window is judged against: the average day over the same number of days just
   before it (clipped at the data start; null when fewer than min(n, 7) earlier days exist, e.g. "All data") */
const prevNeed = n => Math.min(n, 7);
function prevMean(s, a, n) {
  return a < prevNeed(n) ? null : rollN(s, a - 1, Math.min(n, a));
}
const prevSpan = w => spanText(Math.max(0, w.a - w.n), w.a - 1);
/* lift = mean over the health window vs the previous period's mean; baselines floored so a
   near-zero earlier period can't manufacture a huge multiple */
function liftPair(S, T, w = healthWin()) {
  const smax = Math.max(0, ...S.filter(v => v != null));
  const pS = prevMean(S, w.a, w.n), pT = prevMean(T, w.a, w.n);
  const baseS = pS == null ? null : Math.max(pS, 0.05 * smax, 0.5);
  const baseT = pT == null ? null : Math.max(pT, 1);
  const s = rollN(S, w.b, w.n), t = rollN(T, w.b, w.n);
  return { D: s == null || baseS == null ? null : s / baseS, C: t == null || baseT == null ? null : t / baseT, baseT };
}
/* GSC totals over `win` days ending at `end` */
function gscWin(gs, end, win) {
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
/* one key number: label over value, an optional quiet line under it */
const kpi = (label, value, sub, cls = "", title = "") =>
  `<div class="kpi${cls ? " " + cls : ""}"${title ? ` title="${esc(title)}"` : ""}><div class="k">${label}</div><div class="v">${value}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>`;
const daysTxt = n => `${n} day${n === 1 ? "" : "s"}`;
function modeStatsHtml(st, sel) {
  const w = healthWin();
  let h = "";
  if (!sel) {
    const hl = healthOf(st);
    if (hl) h += hl.sparse || hl.noPrev
      ? kpi("Search → our visits", `<span class="na">Can't judge</span>`, hl.noPrev ? "No earlier period to compare" : "Search too sparse in Google Trends")
      : kpi("Search → our visits", `${liftFmt(hl.D)} → ${liftFmt(hl.C)}`, `vs the ${daysTxt(w.n)} before`);
    const T = st.organic && st.organic.some(v => v > 0) ? st.organic : st.traffic;
    if (T) h += kpi("Organic visits", `<span class="u">${fmt(rollN(T, w.b, w.n) * w.n)}</span>`, daysTxt(w.n), "pages");
  } else {
    const S = sel.mode && sel.mode.kwSeries ? meanSeries(sel.mode.kwSeries) : null;
    if (S && sel.traffic) {
      const lp = liftPair(S, sel.traffic, w);
      h += sparseSearch(S) ? kpi("Search → our visitors", `<span class="na">Can't judge</span>`, "Metro search too sparse")
        : lp.D == null ? kpi("Search → our visitors", `<span class="na">Can't judge</span>`, "No earlier period to compare")
        : kpi("Search → our visitors", `${liftFmt(lp.D)} → ${liftFmt(lp.C)}`, `vs the ${daysTxt(w.n)} before`);
    } else if (!S) h += kpi("Search", `<span class="na">No data</span>`, "No metro search data");
    if (sel.traffic) h += kpi("Metro visitors", fmt(rollN(sel.traffic, w.b, w.n) * w.n), daysTxt(w.n));
  }
  const vf = viewFires(st, sel);
  if (vf.length)
    h += kpi(sel ? "Fires in this metro" : "Fires", String(vf.length), `<b class="fscount">${vf.filter(isImpactful).length}</b> impactful`);
  else if (sel && chartFires(st).length)
    h += kpi("Fires in this metro", "0", "None over 100 acres");
  if (GSC && w.g) {
    const gs = gscOf(st, sel);
    const now = gscWin(gs, w.g.b, w.g.n), prev = gscWin(gs, w.a - 1, w.g.n);
    if (now && (!sel || now.i >= 20)) {
      const dpos = now.pos != null && prev && prev.pos != null ? prev.pos - now.pos : null;
      const tt = `Search Console, web, ${spanText(w.a, w.g.b)} vs the ${w.g.n} days before. CTR ${fpct(now.ctr)}`;
      h += kpi(sel ? `Impressions, “${esc(sel.city)}” queries` : "Google impressions",
        `${fmt(now.i)} ${chg(now.i, prev && prev.i)}`, `${fmt(now.c)} clicks, ${daysTxt(w.g.n)} vs the ${w.g.n} before`, "", tt);
      h += kpi("Avg position",
        fposn(now.pos) + (dpos == null || Math.abs(dpos) < 0.1 ? "" : dpos > 0 ? ` <span class="up">↑${dpos.toFixed(1)}</span>` : ` <span class="dn">↓${(-dpos).toFixed(1)}</span>`),
        `CTR ${fpct(now.ctr)}`, "", tt);
    }
  }
  return h;
}
/* the status pill beside a state's name (the whole state only; a metro view has no status) */
function cardPill(st, sel) {
  const hl = sel ? null : healthOf(st);
  return hl ? `<span class="pill ${STATUS[hl.status].cls}">${STATUS[hl.status].label}</span>` : "";
}
function updateCardHead(card) {
  const st = DATA.states[+card.dataset.si], sel = selOf(card, st);
  card.querySelector(".modestats").innerHTML = modeStatsHtml(st, sel);
  card.querySelector(".cpill").innerHTML = cardPill(st, sel);
}
function buildCards() {
  const grid = document.getElementById("grid");
  grid.innerHTML = DATA.states.map((st, si) => {
    const s = st.stats;
    const msel = st.metros && st.metros.length
      ? `<select class="msel sel" aria-label="Area for ${st.name}"><option value="-1">All of ${st.name}</option>` +
        st.metros.map((m, mi) => `<option value="${mi}">${m.name} metro</option>`).join("") + `</select>`
      : "";
    return `<div class="card" data-si="${si}" data-msel="-1">
      <div class="chead"><h2>${st.name} <span class="ab">${st.abbr}</span></h2><span class="cpill">${cardPill(st, null)}</span>${s ? "" : '<span class="notraffic">No site data in export</span>'}${msel}</div>
      <div class="stats"><div class="modestats">${modeStatsHtml(st, null)}</div></div>
      <div class="chart"></div>
      <details class="about tbl"><summary>Daily numbers</summary><div class="tblwrap"></div></details>
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
      const gh = gs ? `<th>Impressions</th><th>Clicks</th><th>CTR</th><th>Avg position</th><th>Best position, ${GSC.bestDays}d</th><th style="text-align:left">Best query</th>` : "";
      let h = `<table><thead><tr><th>Date</th><th>Visitors</th>${st.kws.map(k => `<th>“${esc(k)}” <span class="lbl">${MODE_LABEL[mode]}</span></th>`).join("")}${gh}</tr></thead><tbody>`;
      for (let i = 0; i < N; i++) {
        const best = gs && gs.b && gs.b[i] != null ? `<td>${fposn(gs.b[i])}</td><td style="text-align:left">${esc(gs.bq[i])}</td>` : `<td>–</td><td>–</td>`;
        const gd = !gs ? "" : gs.i[i] == null ? `<td>–</td><td>–</td><td>–</td><td>–</td><td>–</td><td>–</td>`
          : `<td>${gs.i[i]}</td><td>${gs.c[i]}</td><td>${gs.i[i] ? fpct(gs.c[i] / gs.i[i]) : "–"}</td><td>${fposn(gs.p[i])}</td>` + best;
        h += `<tr><td>${fdateY(DATA.dates[i])}</td><td>${st.traffic ? st.traffic[i] : "–"}</td>${kwS.map(s => `<td>${s.length && s[i] != null ? s[i] : "–"}</td>`).join("")}${gd}</tr>`;
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
        tip.innerHTML = `<div class="d">${st.name}: pages counted</div>` + rows +
          (st.stats ? `<div class="tnote">${fmt(st.stats.total)} users since ${fdate(DATA.dates[0])}</div>` : "");
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
      updateCardHead(card);
      renderCard(card);
    });
    attachHover(card);
  });
}

function updateModeStats() {
  document.querySelectorAll(".card[data-si]").forEach(updateCardHead);
}

function renderCard(card, G = chartGeom()) {
  const st = DATA.states[+card.dataset.si];
  const sel = selOf(card, st);
  card.querySelector(".chart").innerHTML = renderChart(st, sel, G);
  const fc = card.querySelector(".fscount");
  if (fc) fc.textContent = viewFires(st, sel).filter(isImpactful).length;
}

let renderedW = 0;
function renderAll() {
  tip.style.display = "none";
  const G = chartGeom();
  renderedW = G.w;
  document.querySelectorAll(".card[data-si]").forEach(card => renderCard(card, G));
}
/* a new date pick re-judges SEO health too: card headers and the overview */
function rangeChanged() {
  renderAll();
  updateModeStats();
  buildOverview();
}

function openState(key) {
  stateFilter = key;
  const sf = document.getElementById("statef");
  if (sf) sf.value = key;
  applyStateFilter();
  const card = document.querySelector(`.card[data-si]:not([hidden])`);
  card && card.scrollIntoView({ behavior: "smooth", block: "start" });
}
const sentenceCase = t => { t = String(t); return t.charAt(0).toUpperCase() + t.slice(1); };
const esc = v => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/* ---------- overview: SEO health ---------- */
const STATUS = {
  out:   { label: "Outperforming", cls: "st-out",   color: "var(--good)" },
  track: { label: "Tracking",      cls: "st-track", color: "var(--neutral)" },
  miss:  { label: "Missing demand", cls: "st-miss", color: "var(--bad)" },
  low:   { label: "Can't judge yet", cls: "st-low", color: "var(--neutral)" },
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
   no reliable level to compare, so its lift can't be judged. */
const FRESH0 = N - 15;
/* share of days (before that fresh tail) on which Google Trends reported any searches */
function trendsShare(S) {
  const v = S.slice(0, FRESH0).filter(x => x != null);
  return v.length ? v.filter(x => x > 0).length / v.length : 0;
}
const sparseSearch = S => trendsShare(S) < 0.5;
/* cached per state for the current health window; a new date pick starts a fresh cache */
const _health = new Map();
let _healthKey = "";
function healthOf(st) {
  const w = healthWin(), wk = `${w.a}:${w.b}`;
  if (wk !== _healthKey) { _health.clear(); _healthKey = wk; }
  if (_health.has(st.key)) return _health.get(st.key);
  const kwS = st.modes.state && st.modes.state.kwSeries;
  const T = st.organic && st.organic.some(v => v > 0) ? st.organic : st.traffic;
  let h = null;
  if (kwS && T) {
    const S = meanSeries(kwS);
    const { D, C, baseT } = liftPair(S, T, w);
    const noPrev = w.a < prevNeed(w.n);
    const totalT = T.reduce((a, b) => a + (b || 0), 0);
    /* rough visits/week we'd have had if our traffic had risen as much as search did */
    const missed = D != null && C != null && D > C ? (D - C) * baseT * 7 : 0;
    let g = null;
    const gw = st.gsc && st.gsc.web;
    if (GSC && gw && w.g && gw.i.some(v => v != null)) {
      /* GSC lags ~2 days, so its side stops at its last complete day; demand re-measured on those same days,
         each against the same number of days immediately before the window */
      const smax = Math.max(0, ...S.filter(v => v != null));
      const pS = prevMean(S, w.a, w.g.n), pI = prevMean(gw.i, w.a, w.g.n), pC = prevMean(gw.c, w.a, w.g.n);
      const baseS = pS == null ? null : Math.max(pS, 0.05 * smax, 0.5);
      const sw = rollN(S, w.g.b, w.g.n);
      const iw = rollN(gw.i, w.g.b, w.g.n), cw = rollN(gw.c, w.g.b, w.g.n);
      const now = gscWin(gw, w.g.b, w.g.n);
      g = { I: iw == null || pI == null ? null : iw / Math.max(pI, 1),
            C: cw == null || pC == null ? null : cw / Math.max(pC, 1),
            Dg: sw == null || baseS == null ? null : sw / baseS, ctr: now && now.ctr, pos: now && now.pos,
            low: gw.i.reduce((a, v) => a + (v || 0), 0) < 300 };
    }
    const sparse = sparseSearch(S);
    h = { st, D, C, ratio: D > 0 && C != null ? C / D : null, status: statusOf(D, C, totalT < 300 || sparse || noPrev),
          sparse, share: trendsShare(S), noPrev, totalT, tSum: Math.round((rollN(T, w.b, w.n) || 0) * w.n), missed: sparse ? 0 : missed, g };
  }
  _health.set(st.key, h);
  return h;
}

/* why states are held back as "can't judge yet", grouped by reason, for the summary pill's tooltip */
function lowTip(list) {
  const why = h => h.noPrev ? "prev" : h.sparse ? "sparse" : h.totalT < 300 ? "traffic" : "none";
  const groups = {
    sparse: ["Too few searches in Google Trends", "Searches are reported on only this share of days; a state needs at least half to have a reliable level to compare against.",
      h => `${Math.round(h.share * 100)}% of days`],
    traffic: ["Too little traffic", "Visits from search since " + fdate(DATA.dates[0]) + "; a state needs at least 300.", h => fmt(h.totalT) + " visits"],
    prev: ["No earlier period", "These dates start at the beginning of the data, so there is nothing before them to compare with. Pick a shorter range.", () => ""],
    none: ["No search signal in these dates", "Google Trends reported no searches for the state over the picked dates.", () => ""],
  };
  return `<div class="d">Can't judge yet<span class="lbl">${list.length} state${list.length === 1 ? "" : "s"}</span></div>` +
    Object.entries(groups).map(([k, [title, note, val]]) => {
      const hs = list.filter(h => why(h) === k);
      return hs.length ? `<div class="lowg"><b>${title}</b><div class="tnote">${note}</div>` +
        hs.map(h => `<div class="row"><span class="n">${esc(h.st.name)}</span><span class="v">${val(h)}</span></div>`).join("") + `</div>` : "";
    }).join("") +
    `<div class="tnote">They're left out of the table until there's enough data to compare.</div>`;
}

/* the likely reason, read off Search Console (impressions = were we shown; clicks = were we chosen) */
function whyOf(h) {
  const g = h.g;
  if (!g || g.low || g.Dg == null || g.I == null) return `<span class="lbl">No Search Console signal</span>`;
  const why = (k, d) => `<span class="whyk">${k}</span><span class="whyd">${d}</span>`;
  if (g.I / g.Dg < 0.6)
    return why("Losing visibility", `Google showed us ${liftFmt(g.I)} as often as before while searches ran ${liftFmt(g.Dg)} their earlier level`);
  if (g.C != null && g.I > 0 && g.C / g.I < 0.6)
    return why("Shown, not clicked", `Shown ${liftFmt(g.I)} as often as before but clicked ${liftFmt(g.C)} as often`);
  if (g.C != null && h.D != null && g.C >= 0.8 * h.D)
    return why("Google clicks kept pace", `Clicks ${liftFmt(g.C)} their earlier level, in line with searches; the gap is outside Google search`);
  return why("Visibility and clicks both slipped", `Shown ${liftFmt(g.I)} as often as before, clicked ${liftFmt(g.C)} as often`);
}

const QPRESETS = {
  dv: { label: "Search demand → our visibility", q: "Did Google show us more as searching rose?",
        desc: "Each dot is a state. Across: search demand. Up: how often Google showed our pages. Both are compared with the same number of days immediately before.",
        x: "Search demand (Trends)", y: "Our impressions (Search Console)", xs: "Search", ys: "Impressions",
        pick: h => h.g && ({ x: h.g.Dg, y: h.g.I, low: h.g.low || h.sparse }) },
  dc: { label: "Search demand → our traffic", q: "Did our traffic rise with search demand?",
        desc: "Each dot is a state. Across: search demand. Up: our organic traffic. Both are compared with the same number of days immediately before.",
        x: "Search demand (Trends)", y: "Our organic traffic", xs: "Search", ys: "Our traffic",
        pick: h => ({ x: h.D, y: h.C, low: h.status === "low" }) },
  vc: { label: "Our visibility → our clicks", q: "When Google showed us, did people click?",
        desc: "Each dot is a state. Across: how often Google showed our pages. Up: how often people clicked. Both are compared with the same number of days immediately before.",
        x: "Our impressions (Search Console)", y: "Our clicks (Search Console)", xs: "Impressions", ys: "Clicks",
        pick: h => h.g && ({ x: h.g.I, y: h.g.C, low: h.g.low }) },
};
let qpreset = GSC ? "dv" : "dc";

function stateChip(h, val) {
  return `<button class="schip orow" data-key="${h.st.key}">${h.st.name}<span class="lbl"> ${val}</span></button>`;
}

/* a wide table: scrolls sideways in its own box; a phone caption says so, and the right edge fades while more is hidden */
const hwrap = t => `<div class="hscroll wide"><div class="swipe">Swipe sideways for every column.</div><div class="hsin">${t}</div></div>`;
function wireHScroll(root) {
  root.querySelectorAll(".hscroll").forEach(box => {
    const sc = box.querySelector(".hsin");
    const upd = () => box.classList.toggle("more", sc.scrollLeft + sc.clientWidth < sc.scrollWidth - 2);
    sc.addEventListener("scroll", upd, { passive: true });
    if (window.ResizeObserver) new ResizeObserver(upd).observe(sc);
    upd();
  });
}

/* tooltip placement shared by the overview's hover readouts */
function placeTip(e) {
  tip.style.display = "block";
  let tx = e.clientX + 14, ty = e.clientY + 12;
  if (tx + tip.offsetWidth > innerWidth - 8) tx = e.clientX - tip.offsetWidth - 14;
  if (ty + tip.offsetHeight > innerHeight - 8) ty = e.clientY - tip.offsetHeight - 12;
  tip.style.left = tx + "px"; tip.style.top = ty + "px";
}

const PHONE_Q = matchMedia("(max-width: 700px)");
function buildOverview() {
  const sec = document.getElementById("overview");
  const healths = DATA.states.map(healthOf);
  if (!healths.some(Boolean)) { sec.hidden = true; return; }
  sec.hidden = false;
  const w = healthWin();
  const gSpan = GSC && w.g ? spanText(w.a, w.g.b) : null;
  document.getElementById("osub").textContent =
    `Are our visits from search keeping up with search demand? Each state over ${spanText(w.a, w.b)} (${w.n} complete day${w.n > 1 ? "s" : ""}), compared with the ${daysTxt(w.n)} before.${w.a < prevNeed(w.n) ? " The data has no earlier days, so nothing can be judged. Pick a shorter range." : ""}`;

  const hs = healths.filter(Boolean);
  const by = st => hs.filter(h => h.status === st);
  const miss = by("miss").sort((a, b) => b.missed - a.missed);
  const hasG = GSC && hs.some(h => h.g);

  /* the status counts, most actionable first */
  let sum = `<span class="slead">${hs.length} state${hs.length === 1 ? "" : "s"}</span>`;
  [["miss", "missing demand"], ["track", "tracking"], ["out", "outperforming"], ["low", "can't judge yet"]].forEach(([k, l]) => {
    const n = by(k).length;
    if (n) sum += k === "low"
      ? `<span class="pill ${STATUS[k].cls} sumlow" tabindex="0" role="button" aria-label="${n} can't judge yet: show why">${n} ${l}</span>`
      : `<span class="pill ${STATUS[k].cls}">${n} ${l}</span>`;
  });
  if (!miss.length) sum += `<span class="snone">No state is missing demand.</span>`;
  document.getElementById("ssum").innerHTML = sum;
  const lowPill = document.querySelector("#ssum .sumlow");
  if (lowPill) {
    const show = e => {
      tip.innerHTML = lowTip(by("low"));
      const r = lowPill.getBoundingClientRect();
      placeTip(e && e.type === "pointermove" ? e : { clientX: r.left, clientY: r.bottom });
    };
    lowPill.addEventListener("pointermove", show);
    lowPill.addEventListener("click", show);   /* touch screens have no hover */
    lowPill.addEventListener("focus", show);
    ["pointerleave", "blur"].forEach(ev => lowPill.addEventListener(ev, () => { tip.style.display = "none"; }));
  }

  /* one table: states behind demand first (biggest shortfall on top), then ahead of it, then in line */
  const rows = [...miss, ...by("out").sort((a, b) => b.ratio - a.ratio), ...by("track").sort((a, b) => b.ratio - a.ratio)];
  /* for states that aren't behind there's no gap to explain: just describe what Search Console saw */
  const gscRead = h => !h.g || h.g.low || h.g.I == null ? `<span class="lbl">No Search Console signal</span>`
    : `<span class="whys">Shown ${liftFmt(h.g.I)} as often as before${h.g.C != null ? `, clicked ${liftFmt(h.g.C)} as often` : ""}</span>`;

  /* phones: the key number sits right after the pinned state name, so it shows before any sideways scrolling */
  const keyFirst = PHONE_Q.matches;
  const stCol = `<col style="width:148px">`, keyCol = `<col style="width:120px">`;
  const stTh = `<th class="l">Status</th>`;
  const keyTh = `<th title="Each as a multiple of its level over the same number of days immediately before the dates picked at the top (1× = no change). Visits = our organic visits from search engines (PostHog), which track Google's Search Console clicks within a few percent.">Search → visits<span class="thsub">× previous period</span></th>`;
  const stTd = h => `<td class="stcell"><span class="pill ${STATUS[h.status].cls}">${STATUS[h.status].label}</span></td>`;
  const keyTd = h => `<td>${liftFmt(h.D)} → ${liftFmt(h.C)}</td>`;
  let html = rows.length
    ? hwrap(`<table class="mtab score"><colgroup><col style="width:${keyFirst ? 116 : 136}px">${keyFirst ? keyCol + stCol : stCol + keyCol}<col style="width:104px"><col></colgroup>
       <thead><tr><th class="l">State</th>${keyFirst ? keyTh + stTh : stTh + keyTh}
       <th>Missed visits<span class="thsub">per week, est.</span></th>
       <th class="l why">${hasG ? `What Search Console shows<span class="thsub">${gSpan || "No complete days yet"}</span>` : ""}</th></tr></thead><tbody>` +
      rows.map(h => `<tr class="orow mrow" data-key="${h.st.key}" tabindex="0">
        <td class="mn">${h.st.name}</td>
        ${keyFirst ? keyTd(h) + stTd(h) : stTd(h) + keyTd(h)}
        ${h.status === "miss" ? `<td class="bad">${fmt(h.missed)}</td>` : `<td class="lbl">–</td>`}
        <td class="kw why">${!hasG ? "" : h.status === "miss" ? whyOf(h) : gscRead(h)}</td></tr>`).join("") + `</tbody></table>`)
    : `<div class="mempty">No state has enough search and traffic over these dates to judge.</div>`;

  const low = by("low");
  if (low.length)
    html += `<details class="sline squiet"><summary><span class="slabel">Can't judge yet</span>
      <span class="lbl">${low.length} state${low.length > 1 ? "s" : ""} with too few searches in Google Trends, too little traffic, or no earlier period to compare with</span></summary>
      ${low.map(h => stateChip(h, h.noPrev ? "no earlier period" : h.sparse ? "sparse search" : "low traffic")).join("")}</details>`;
  document.getElementById("oscore").innerHTML = html;
  wireHScroll(document.getElementById("oscore"));

  /* how this section is calculated (its dates follow the picker) */
  document.getElementById("oabout").innerHTML = `
    <p>Each state's search demand and our visits are averaged over ${spanText(w.a, w.b)} (${w.n} complete day${w.n > 1 ? "s" : ""};
    the latest day is still partial and left out), then compared with the same number of days immediately before
    (${w.a < prevNeed(w.n) ? "none in the data for these dates" : prevSpan(w)}). 1× means no change; 2× means twice the earlier level.
    Change the dates with the date button at the top.</p>
    <p><b>Visits</b> are our organic visits: visitors arriving from a search engine (Google, Bing, DuckDuckGo, Yahoo,
    Ecosia, Brave), counted by PostHog. They track Google's Search Console clicks within a few percent. <b>Clicks</b> on
    this page always mean Search Console clicks from Google.</p>
    <h4>Status</h4>
    <dl class="tags">
      <dt><span class="pill st-miss">Missing demand</span></dt><dd>Visits ÷ search is below 0.6: our traffic fell behind search, whether search rose or fell.</dd>
      <dt><span class="pill st-track">Tracking</span></dt><dd>Visits ÷ search is between 0.6 and 1.25.</dd>
      <dt><span class="pill st-out">Outperforming</span></dt><dd>Visits ÷ search is above 1.25.</dd>
      <dt><span class="pill st-low">Can't judge yet</span></dt><dd>Google Trends reports too few searches in the state to judge,
      our traffic there is too low, or the dates have no earlier period to compare with (for example "All data"). These
      states are left out of the table, because their multiple would be misleading.</dd>
    </dl>
    <h4>Columns</h4>
    <dl>
      <dt>Missed visits per week</dt><dd>A rough estimate for states missing demand: (search multiple − our multiple) × our average day in the previous period × 7.</dd>` +
    (hasG ? `
      <dt>What Search Console shows</dt><dd>Our own labels (Google doesn't supply them), read from Search Console${gSpan ? ` over ${gSpan}` : ""},
      up to its last complete day. Search Console runs about two days behind. For states missing demand it names the
      likely reason:
      <ul>
        <li><b>Losing visibility</b>: our impressions fell well behind search (impressions ÷ search below 0.6). Points to
        a ranking or indexing gap.</li>
        <li><b>Shown, not clicked</b>: our clicks fell well behind our impressions (clicks ÷ impressions below 0.6). Points
        to a title, snippet or position gap.</li>
        <li><b>Google clicks kept pace</b>: our Google clicks rose with searching, so the shortfall is in other search
        engines or in tracking.</li>
        <li><b>Visibility and clicks both slipped</b>: none of the above.</li>
      </ul>
      For other states it says how often Google showed and clicked us compared with the previous period.</dd>` : "") + `
    </dl>
    <p>Click a row to open that state's chart. Hover it for the exact numbers.</p>`;

  const qsel = document.getElementById("qpreset");
  if (!qsel.options.length) {
    qsel.innerHTML = Object.entries(QPRESETS).filter(([k]) => k === "dc" || hasG)
      .map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
    qsel.value = qpreset;
    qsel.addEventListener("change", e => { qpreset = e.target.value; renderQuad(DATA.states.map(healthOf)); });
  }
  renderQuad(healths);

  sec.querySelectorAll("#oscore .orow").forEach(el => {
    const h = healthOf(DATA.states.find(x => x.key === el.dataset.key));
    el.addEventListener("click", () => openState(el.dataset.key));
    el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openState(el.dataset.key); } });
    el.addEventListener("pointermove", e => {
      const g = h.g;
      tip.innerHTML = `<div class="d">${h.st.name}<span class="lbl">${spanText(w.a, w.b)} vs the ${daysTxt(w.n)} before</span></div>
        <table class="tt"><tbody>
        <tr><td class="n">Search demand</td><td>${liftFmt(h.D)}</td></tr>
        <tr><td class="n">Our visits from search</td><td>${liftFmt(h.C)}</td></tr>
        <tr><td class="n">Organic visits</td><td>${fmt(h.tSum)}</td></tr>
        <tr><td class="n">Visits ÷ search</td><td>${h.ratio == null ? "–" : h.ratio.toFixed(2) + "×"}</td></tr>
        ${g ? `<tr><td class="n">Google impressions</td><td>${liftFmt(g.I)}</td></tr>
        <tr><td class="n">Google clicks</td><td>${liftFmt(g.C)}</td></tr>
        <tr><td class="n">CTR</td><td>${fpct(g.ctr)}</td></tr>
        <tr><td class="n">Avg position</td><td>${fposn(g.pos)}</td></tr>` : ""}
        </tbody></table>`;
      placeTip(e);
    });
    el.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  });
}

/* status never rides on color alone: good = filled dot, missing demand = down-triangle, tracking / low = hollow ring */
function statusMark(status, cx, cy) {
  const x = cx.toFixed(1), y = cy.toFixed(1);
  if (status === "miss")
    return `<path d="M ${(cx - 6).toFixed(1)} ${(cy - 4).toFixed(1)} L ${(cx + 6).toFixed(1)} ${(cy - 4).toFixed(1)} L ${x} ${(cy + 6).toFixed(1)} Z" fill="var(--bad)" stroke="var(--surface)" stroke-width="1.5" stroke-linejoin="round"/>`;
  if (status === "out")
    return `<circle cx="${x}" cy="${y}" r="5" fill="var(--good)" stroke="var(--surface)" stroke-width="2"/>`;
  return `<circle cx="${x}" cy="${y}" r="4.5" fill="var(--surface)" stroke="var(--neutral)" stroke-width="2"/>`;
}

/* the quadrant is drawn at its on-screen width (so chart text keeps its real size on a phone) */
const quadW = () => { const el = document.getElementById("oquad"); return Math.round(Math.max(300, Math.min(470, (el && el.clientWidth) || 420))); };
let renderedQW = 0;
function renderQuad(healths) {
  const P = QPRESETS[qpreset];
  const QW = renderedQW = quadW(), QH = Math.round(QW * 0.78) + 14, QL = 48, QR = QW < 380 ? 20 : 46, QT = 28, QB = 40;
  const ui = `font-family="Figtree, system-ui, sans-serif"`;
  const pts = healths.filter(Boolean).map(h => {
    const v = P.pick(h);
    if (!v || v.x == null || v.y == null) return null;
    return { h, x: v.x, y: v.y, ratio: v.x > 0 ? v.y / v.x : null, status: statusOf(v.x, v.y, v.low) };
  }).filter(p => p && p.status !== "low");
  const w = healthWin(), wTxt = spanText(w.a, w.b), gTxt = w.g ? spanText(w.a, w.g.b) : null;
  const CAP = 24;
  /* the side panel: the chart's question, one line on how it's built, a key to the marks, then the long note */
  document.getElementById("oqtitle").textContent = P.q;
  document.getElementById("oqq").textContent = P.desc;
  const mk = s => `<svg width="16" height="16" viewBox="-8 -8 16 16" aria-hidden="true">${statusMark(s, 0, 0)}</svg>`;
  const nOf = s => pts.filter(p => p.status === s).length;
  document.getElementById("oqleg").innerHTML = pts.length ? `
    <li>${mk("miss")}<span>Missing demand <span class="lbl">(${nOf("miss")}), well below the dashed line</span></span></li>
    <li>${mk("track")}<span>Tracking <span class="lbl">(${nOf("track")}), near it</span></span></li>
    <li>${mk("out")}<span>Outperforming <span class="lbl">(${nOf("out")}), well above it</span></span></li>` : "";
  const gT = gTxt ? `${gTxt} (Search Console's complete days)` : "Search Console's complete days (none in these dates yet)";
  document.getElementById("oqnote").innerHTML = {
      dv: `<p>x = search demand, y = how often Google showed our pages (Search Console impressions), over ${gT}, each as a
        multiple of the same number of days immediately before. Below the diagonal, our visibility fell behind searching, which
        points to a ranking or indexing gap.</p>`,
      dc: `<p>x = search demand, y = our organic traffic, over ${wTxt}, each as a multiple of the same number of days immediately before. Below the
        diagonal, our traffic fell behind searching.</p>`,
      vc: `<p>x = impressions, y = clicks, both from Search Console, over ${gT}. Below the diagonal, clicks fell behind
        impressions (fewer clicks per impression than before), which points to a title, snippet or position problem.</p>`,
    }[qpreset] + `<p>The 1× lines mark no change from the previous period. Each dot's color and shape come from this chart's own ratio
    (y ÷ x), using the same 0.6 and 1.25 cut-offs as the table. A state past ${CAP}× is drawn scaled down along its own
    line from the origin, so it stays on the correct side of the diagonal, and is labelled with both values. States whose
    search is too sparse to judge are left off.</p>
    <p>Hover a dot for exact values. Click it to open the state.</p>`;
  if (!pts.length) {
    document.getElementById("oquad").innerHTML = `<div class="mempty">${qpreset !== "dc" && !gTxt
      ? "Search Console has no complete days in these dates yet. It runs about two days behind."
      : "No state has enough data over these dates to plot."}</div>`;
    return;
  }
  const allLifts = pts.flatMap(p => [p.x, p.y]).filter(v => v > 0);
  /* cap the axis so one extreme state (e.g. 100×+) can't squash everyone else into a corner */
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
    g += `<text x="${LX(t)}" y="${QH - QB + 16}" text-anchor="middle" font-size="11.5" fill="var(--muted)" ${ui}>${t}×</text>`;
    g += `<text x="${QL - 7}" y="${LY(t) + 4}" text-anchor="end" font-size="11.5" fill="var(--muted)" ${ui}>${t}×</text>`;
  });
  g += `<line x1="${LX(lo)}" y1="${LY(lo)}" x2="${LX(hi)}" y2="${LY(hi)}" stroke="var(--muted)" stroke-dasharray="5 4" opacity="0.7"/>`;
  g += `<text x="${QW - QR}" y="${QH - QB - 8}" text-anchor="end" font-size="11.5" font-weight="600" fill="var(--bad-ink)" ${ui}>↓ Falling behind</text>`;
  /* above the plot, where no dot or dot label can reach it */
  g += `<text x="${QL}" y="${QT - 12}" font-size="11.5" font-weight="600" fill="var(--good-ink)" ${ui}>↑ Outperforming</text>`;
  g += `<text x="${(QL + QW - QR) / 2}" y="${QH - 6}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--muted)" ${ui}>${P.x}, × previous period</text>`;
  g += `<text x="13" y="${(QT + QH - QB) / 2}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--muted)" ${ui} transform="rotate(-90 13 ${(QT + QH - QB) / 2})">${P.y}, × previous period</text>`;

  /* red dots always get a label; the rest are placed greedily so labels never overlap */
  const placed = [];
  [...pts].sort((a, b) => ({ miss: 0, out: 1, track: 2 })[a.status] - ({ miss: 0, out: 1, track: 2 })[b.status] || b.x - a.x)
    .forEach(pt => {
      const h = pt.h;
      const [rx, ry] = onRay(pt.x, pt.y);
      const cx = LX(rx), cy = LY(ry);
      const off = pt.x > hi || pt.y > hi;
      const text = off ? `${h.st.abbr} ${liftFmt(pt.x)}→${liftFmt(pt.y)}` : h.st.abbr;
      const w = text.length * 7 + 4;
      let bx = cx + 8;
      if (bx + w > QW - 2) bx = cx - 8 - w;
      const by = cy - 9;
      let lbl = "";
      if (pt.status === "miss" || !placed.some(p => bx < p.bx + p.w && bx + w > p.bx && by < p.by + 12 && by + 12 > p.by)) {
        placed.push({ bx, by, w });
        lbl = `<text x="${bx.toFixed(1)}" y="${(cy + 4).toFixed(1)}" font-size="11.5" font-weight="600" fill="${pt.status === "miss" ? "var(--bad-ink)" : "var(--ink-2)"}" ${ui}>${text}</text>`;
      }
      g += `<g class="dot orow" data-key="${h.st.key}" data-pi="${pts.indexOf(pt)}">
        ${statusMark(pt.status, cx, cy)}${lbl}</g>`;
    });
  document.getElementById("oquad").innerHTML =
    `<svg viewBox="0 0 ${QW} ${QH}" role="img" aria-label="${P.label}, by state, ${wTxt}">${g}</svg>`;
  document.querySelectorAll("#oquad .dot").forEach(d => {
    d.addEventListener("pointermove", e => {
      const pt = pts[+d.dataset.pi];
      tip.innerHTML = `<div class="d">${esc(pt.h.st.name)} <span class="pill ${STATUS[pt.status].cls}">${STATUS[pt.status].label}</span></div>
        <table class="tt"><tbody>
          <tr><td class="n">${P.xs}</td><td>${liftFmt(pt.x)}</td></tr>
          <tr><td class="n">${P.ys}</td><td>${liftFmt(pt.y)}</td></tr>
        </tbody></table>
        <div class="tnote">${qpreset === "dc" ? wTxt : gTxt}, vs the same number of days immediately before</div>`;
      placeTip(e);
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
  return parts.filter(Boolean).join(", ");
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
      legend += `<div class="li"><span class="swb" style="background:${KW_META[top.k].color};opacity:.65"></span>Top term: ${tplTerms(st, KW_META[top.k].tpl)}</div>`;
    }
  });
  if (st.metros.some(m => !topTermToday(m)))
    legend += `<div class="li"><span class="swb" style="background:var(--chip-bg);border:1px solid var(--border)"></span>No term registering today</div>`;
  if (map.gap)
    legend += `<div class="li"><span class="swb" style="background:var(--grid)"></span>Not in any of this state's listed markets</div>`;
  if (activeFires.length)
    legend += `<div class="li">${legendSwatch("fires")}Active fire, impactful</div>
      <div class="li">${legendSwatch("fires_h")}Active fire, not impactful</div>`;
  mapEl.innerHTML = `<div class="mtitle">${st.name} by metro area</div>
    <div class="msub">Each metro is shaded by its strongest search term on ${fdate(DATA.dates[lastFull])}, the latest full day. Diamonds are fires burning now. Hover a metro for its numbers, or click it to open its chart.</div>
    <div class="mapbox"><svg viewBox="0 0 ${map.w} ${map.h}" role="img" aria-label="${st.name} metros by top search term"><path class="under" d="${map.outline}"/>${paths}<path class="outline" d="${map.outline}"/>${firePaths}</svg>
    <div class="maplegend">${legend}</div></div>`;

  mapEl.querySelectorAll("g.fmk").forEach(p => {
    const f = activeFires[+p.dataset.fi];
    p.addEventListener("pointermove", e => {
      const pop = f.p ? `${fmt(f.p[impact.ring])} ppl ≤${impact.ring}mi` : "pop n/a";
      tip.innerHTML = `<div class="d">${legendSwatch(isImpactful(f) ? "fires" : "fires_h")} ${f.t} fire<span class="lbl">active</span></div>
        <div class="row"><span class="n">Started ${fdate(f.d)}</span><span class="v">${f.a ? fmt(f.a) + " ac" : ""} · ${pop}</span></div>`;
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
      let body = `<tr><td class="n"><span class="sw">${legendSwatch("traffic")}</span>Our visitors, last 7 days</td><td>${fmt(vis7)}</td><td></td></tr>`;
      const kwS = m.mode && m.mode.kwSeries;
      if (!kwS) body += `<tr><td class="n" colspan="3" style="color:var(--muted)">No search data for this metro</td></tr>`;
      else {
        const live = kwS.map((s, k) => ({ s, k })).filter(x => x.s.length > i && x.s[i] > 0).sort((a, b) => b.s[i] - a.s[i]);
        if (!live.length)
          body += `<tr><td class="n" colspan="3" style="color:var(--muted)">${kwS.every(s => s[i] == null) ? "Search data missing for this day" : "No search term registering"}</td></tr>`;
        live.forEach(x => {
          body += `<tr><td class="n"><span class="sw">${legendSwatch(KW_META[x.k])}</span>${(m.kws || st.kws)[x.k]}</td><td>${Math.round(x.s[i] * 10) / 10}</td>${cell(d7(x.s))}</tr>`;
        });
      }
      const g7 = GSC ? gscWin(m.gsc && m.gsc[gscType], GSC_LAST, 7) : null;
      if (g7 && g7.i > 0)
        body += `<tr><td class="n" colspan="3" style="padding-top:6px"><span class="sw">${legendSwatch({ color: "var(--gi)" })}</span>Search Console, “${esc(m.city)}” queries, 7 days: <b>${fmt(g7.i)}</b> impressions, <b>${fmt(g7.c)}</b> clicks</td></tr>`;
      tip.innerHTML = `<div class="d">${m.name} metro</div>
        <table class="tt"><thead><tr><th></th><th>${fdate(DATA.dates[i])}</th><th>Change, 7 days</th></tr></thead>
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
    `Metros where wildfire searches jumped this week, and whether our visitors from there rose with them. This week is ${fdate(DATA.dates[end - SURGE_WIN + 1])} – ${fdate(DATA.dates[end])}, compared with the week before.`;
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
  /* phones: the surge sits right after the pinned-width metro name, so it shows before any sideways scrolling */
  const ph = PHONE_Q.matches;
  const termCol = showTerm ? '<col style="width:24%">' : "", termTh = showTerm ? '<th class="l">Surging term</th>' : "";
  const termTd = r => showTerm ? `<td class="kw">${(r.m.kws || r.st.kws)[r.k]}</td>` : "";
  const xCol = '<col style="width:104px">', xTh = '<th>Searches<span class="thsub">vs last week</span></th>';
  const xTd = r => `<td class="xv">↑${liftFmt(r.x)}</td>`;
  document.getElementById("msurge").innerHTML = rows.length
    ? hwrap(`<table class="mtab surge"><colgroup><col>${ph ? xCol + termCol : termCol + xCol}<col style="width:150px"><col style="width:150px"></colgroup>
       <thead><tr><th class="l">Metro</th>${ph ? xTh + termTh : termTh + xTh}
       <th>Our visitors a day<span class="thsub">last week → this week</span></th><th class="l">Status</th></tr></thead><tbody>` +
      rows.map(r => `<tr class="mrow" data-si="${r.si}" data-mi="${r.mi}" tabindex="0"
          data-tip="${esc(r.m.name)}: “${esc((r.m.kws || r.st.kws)[r.k])}” averaged ${v(r.prev)} last week and ${v(r.now)} this week, on the metro's own 0–100 index">
        <td class="mn">${r.m.name}<span class="ab">${r.st.abbr}</span></td>
        ${ph ? xTd(r) + termTd(r) : termTd(r) + xTd(r)}
        <td>${v(r.tPrev)} → ${v(r.tNow)}</td>
        <td class="stcell"><span class="pill ${r.captured ? "st-out" : "st-miss"}">${r.captured ? "Capturing" : "Not capturing"}</span></td></tr>`).join("") +
      `</tbody></table>`)
    : `<div class="mempty">No metro's search jumped 1.5× or more this week with meaningful volume.</div>`;
  wireHScroll(document.getElementById("msurge"));

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
  sel.innerHTML = `<option value="-1">Any term</option>` +
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
    `Pages that could earn more clicks from searches they already show up in, biggest gain first. Google web search, ${fdate(GSC.topWindow[0])} – ${fdate(GSC.topWindow[1])}, compared with the ${WIN} days before.`;
  const known = new Set(DATA.states.map(x => x.key));
  const TAG = { "page 2+": "st-miss", "weak snippet": "st-low", "new demand": "st-track", "old page": "st-low" };
  const trend = g => {
    const r = g.i0 ? g.i / g.i0 : Infinity;
    if (r >= 20) return `<span class="pill st-track">New</span>`;
    /* one format with the rest of the page: ↑/↓ and a multiple of the 14 days before */
    return `<span class="trend">${chg(g.i, g.i0)}</span>`;
  };
  /* phones: extra clicks sit right after the page name, so they show before any sideways scrolling */
  const ph = PHONE_Q.matches;
  const potCol = '<col style="width:96px">', potTh = '<th>Extra clicks<span class="thsub">per week</span></th>';
  const potTd = g => `<td class="xv">${fmt(g.pot)}</td>`;
  document.getElementById("tqlist").innerHTML = tq.groups.length
    ? hwrap(`<table class="mtab tqtab"><colgroup><col style="width:24%">${ph ? potCol : ""}<col><col style="width:84px"><col style="width:124px">${ph ? "" : potCol}<col style="width:200px"></colgroup>
       <thead><tr><th class="l">Page</th>${ph ? potTh : ""}<th class="l">Biggest query</th><th class="l">Queries</th><th>Page impressions<span class="thsub">last ${WIN} days</span></th>${ph ? "" : potTh}<th class="l">Reason</th></tr></thead>` +
      tq.groups.map((g, gi) => `<tbody class="tqg">
        <tr class="${known.has(g.state) ? "mrow tqrow" : "tqrow-x"}" data-key="${g.state || ""}" data-gi="${gi}" tabindex="0">
          <td class="mn">${esc(g.label)}${g.state_label ? `<span class="ab">${g.state_label}</span>` : ""}</td>
          ${ph ? potTd(g) : ""}
          <td class="kw" title="${esc(g.queries[0].q)}: ${fmt(g.queries[0].i)} impressions at position ${fposn(g.queries[0].pos)}, ${fmt(g.queries[0].c)} clicks">${esc(g.queries[0].q)}</td>
          <td class="l">${g.n > 1 ? `<button class="more" data-gi="${gi}" aria-expanded="false" aria-label="Show the biggest of ${fmt(g.n)} queries">${fmt(g.n)}</button>` : "1"}</td>
          <td>${fmt(g.i)} ${trend(g)}</td>
          ${ph ? "" : potTd(g)}
          <td class="stcell">${g.tags.map(t => `<span class="pill ${TAG[t] || "st-low"}">${sentenceCase(t)}</span>`).join(" ")}</td></tr>
        <tr class="sub" data-gi="${gi}" hidden><td colspan="6" class="subwrap">
          <table class="qtab"><thead><tr><th class="l">Query</th><th>Avg position</th><th>Impressions, 14d</th><th>Clicks, 14d</th>
            <th title="Impressions × the click rate this site usually gets at that position (at position 5 for queries below page 1)">Expected clicks, 14d</th>
            <th>Extra clicks a week</th></tr></thead><tbody>
          ${g.queries.map(q => {
            const e = q.e != null ? q.e : q.c + q.pot * (WIN / 7);
            return `<tr><td class="l kw" title="${esc(q.q)}">${esc(q.q)}</td>
              <td>${fposn(q.pos)}${q.pos > 10 ? ` <span class="lbl">page 2+</span>` : ""}</td>
              <td>${fmt(q.i)}</td><td>${fmt(q.c)}</td>
              <td>~${fmt(e)}${q.pos > 10 ? ` <span class="lbl">at #5</span>` : ""}</td>
              <td class="xv">${q.pot >= 1 ? fmt(q.pot) : "–"}</td></tr>`;
          }).join("")}
          </tbody></table>
          ${g.n > g.queries.length ? `<div class="qmore lbl">+${fmt(g.n - g.queries.length)} smaller queries not shown</div>` : ""}
        </td></tr>
        </tbody>`).join("") + `</table>`)
    : `<div class="mempty">No page has a meaningful click opportunity right now.</div>`;
  wireHScroll(document.getElementById("tqlist"));

  const tbl = document.getElementById("tqlist");
  tbl.querySelectorAll("button.more").forEach(btn => btn.addEventListener("click", e => {
    e.stopPropagation();
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
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
        <table class="tt"><thead><tr><th></th><th>Last ${WIN} days</th><th>${WIN} days before</th></tr></thead><tbody>
        <tr><td class="n">Impressions</td><td>${fmt(g.i)}</td><td>${fmt(g.i0)}</td></tr>
        <tr><td class="n">Clicks</td><td>${fmt(g.c)}</td><td>${prev(fmt(g.c0))}</td></tr>
        <tr><td class="n">CTR</td><td>${fpct(g.i ? g.c / g.i : null)}</td><td>${prev(fpct(g.i0 ? g.c0 / g.i0 : null))}</td></tr>
        <tr><td class="n">Avg position</td><td>${fposn(g.pos)}</td><td>${prev(fposn(g.pos0))}</td></tr>
        </tbody></table>
        <div class="tnote">${fmt(g.n)} search ${g.n === 1 ? "query lands" : "queries land"} on this page.${known.has(g.state) ? "" : " Its state is not on this dashboard."}</div>`;
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
    if (visible.traffic && traf) rows += row(legendSwatch("traffic"), "Our traffic", `${traf[i]} visits`);
    if (kwS) {
      const on = kwS.map((s, k) => k).filter(k => visible["k" + k] && kwS[k].length);
      const missing = on.every(k => kwS[k][i] == null);
      const pos = on.filter(k => kwS[k][i] > 0).sort((a, b) => kwS[b][i] - kwS[a][i]);
      const zero = on.filter(k => kwS[k][i] === 0);
      pos.forEach(k => { rows += row(legendSwatch(KW_META[k]), kws[k], kwS[k][i]); });
      if (missing && on.length) rows += muted("Search data missing for this day");
      else if (zero.length) rows += muted(`0: ${zero.map(k => kws[k]).join(", ")}`);
    }
    if (visible.fires) {
      const todays = [...(fireMap(st, sel)[i] || [])].sort((a, b) => isImpactful(b) - isImpactful(a));
      todays.slice(0, 3).forEach(f => {
        const pop = f.p ? `${fmt(f.p[impact.ring])} ppl ≤${impact.ring}mi` : "pop n/a";
        rows += row(legendSwatch(isImpactful(f) ? "fires" : "fires_h"), `${f.t} fire started`, `${f.a ? fmt(f.a) + " ac" : ""} · ${pop}`);
      });
      if (todays.length > 3) {
        const rest = todays.slice(3);
        rows += muted(`+${rest.length} more fires (${rest.filter(isImpactful).length} impactful)`);
      }
    }
    const gs = GSC ? gscOf(st, sel) : null;
    if (gs && (visible.gi || visible.gpos || visible.gbest || visible.gctr)) {
      const who = sel ? `, “${esc(sel.city)}” queries` : "";
      if (gs.i[i] == null) rows += muted("Search Console: not in yet (it runs about two days behind)");
      else {
        if (visible.gi) rows += row(legendSwatch({ color: "var(--gi)" }), `Impressions${who}`, `${fmt(gs.i[i])}, ${fmt(gs.c[i])} clicks`);
        if (visible.gpos) rows += row(legendSwatch({ color: "var(--gp)", dash: "0.1 3.6", cap: true }), `Avg position${who}`, fposn(gs.p[i]));
        if (visible.gbest) {
          const b = gs.b ? gs.b[i] : null;
          rows += row(legendSwatch({ color: "var(--gp)", dash: "5 3" }), `Best position, ${GSC.bestDays} days${who}`, fposn(b));
          rows += muted(b == null ? `No query reached ${GSC.bestMin} impressions in the ${GSC.bestDays} days to here`
            : `Best query: “${esc(gs.bq[i])}”, ${fmt(gs.bi[i])} impressions over ${GSC.bestDays} days`);
        }
        if (visible.gctr) rows += row(legendSwatch({ color: "var(--gc)" }), `CTR${who}`, gs.i[i] ? fpct(gs.c[i] / gs.i[i]) : "–");
      }
    }
    tip.innerHTML = `<div class="d">${st.name}${sel ? `, ${sel.name} metro` : ""}<span class="lbl">${fdateY(DATA.dates[i])}</span></div>` + rows;
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

/* ---------- shared date-range picker for the newer tabs ----------
   Same look as the chart-dates button: presets on the left, a start and an end calendar.
   Ranges are inclusive index pairs into DATA.dates.
   opts: { title, presets: [{ key, label, get: () => [r0, r1] }], initial: preset key,
           storageKey (optional, remembers the pick per viewer), minDays (default 1), onChange(range) }
   Returns { el, get() -> { preset, r0, r1 }, refresh() }; refresh() re-evaluates a preset whose
   dates depend on something else (e.g. "previous period") and updates the label, without onChange. */
function makeRangePicker(host, opts) {
  const D0 = DATA.dates[0], D1 = DATA.dates[N - 1], minSpan = (opts.minDays || 1) - 1;
  const ymd = (y, m, d) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const monthOf = iso => { const [y, m] = iso.split("-"); return { y: +y, m: +m - 1 }; };
  const st = { preset: opts.initial, r0: 0, r1: N - 1 }, cal = {};
  const clamp = (r0, r1) => {
    r0 = Math.max(0, Math.min(N - 1 - minSpan, r0));
    return [r0, Math.max(r0 + minSpan, Math.min(N - 1, r1))];
  };
  /* a custom pick that happens to equal a preset is shown as that preset */
  const match = () => (opts.presets.find(p => { const [a, b] = clamp(...p.get()); return a === st.r0 && b === st.r1; }) || { key: "custom" }).key;
  function apply(preset, r0, r1) {
    const p = opts.presets.find(x => x.key === preset);
    if (p) [r0, r1] = p.get();
    [st.r0, st.r1] = clamp(r0, r1);
    st.preset = p ? preset : match();
  }
  const el = document.createElement("details");
  el.className = "pop dpick";
  el.innerHTML = `<summary class="lg dbtn"${opts.title ? ` title="${esc(opts.title)}"` : ""}>
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="1.5" y="2.5" width="11" height="10" rx="1.5"/><line x1="1.5" y1="5.6" x2="12.5" y2="5.6"/><line x1="4.5" y1="1" x2="4.5" y2="3.8"/><line x1="9.5" y1="1" x2="9.5" y2="3.8"/></svg>
      <span class="rplabel"></span><span class="chev" aria-hidden="true"></span></summary>
    <div class="popbody dpbody">
      <div class="dpresets" role="group" aria-label="Date presets">` +
      opts.presets.map(p => `<button type="button" data-p="${p.key}" aria-pressed="false">${p.label}</button>`).join("") + `</div>
      <div class="dcals"><div class="dcal" data-which="start"></div><div class="dcal" data-which="end"></div></div>
    </div>`;
  host.appendChild(el);
  function renderCal(which) {
    const box = el.querySelector(`.dcal[data-which="${which}"]`), v = cal[which];
    const first = new Date(v.y, v.m, 1), days = new Date(v.y, v.m + 1, 0).getDate();
    const s0 = DATA.dates[st.r0], s1 = DATA.dates[st.r1], picked = which === "start" ? s0 : s1;
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
    box.innerHTML = h + `</div>`;
  }
  function sync(resetViews = true) {
    const p = opts.presets.find(x => x.key === st.preset);
    const dates = st.r0 === st.r1 ? fdate(DATA.dates[st.r0]) : `${fdate(DATA.dates[st.r0])} – ${fdate(DATA.dates[st.r1])}`;
    el.querySelector(".rplabel").innerHTML = p ? `${p.label} <span class="lbl">${dates}</span>` : dates;
    el.querySelectorAll("[data-p]").forEach(b => {
      const on = b.dataset.p === st.preset;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    if (resetViews || !cal.start) { cal.start = monthOf(DATA.dates[st.r0]); cal.end = monthOf(DATA.dates[st.r1]); }
    renderCal("start"); renderCal("end");
    if (opts.storageKey) try { localStorage.setItem(opts.storageKey, JSON.stringify(st.preset === "custom"
      ? { p: "custom", from: DATA.dates[st.r0], to: DATA.dates[st.r1] } : { p: st.preset })); } catch (e) {}
  }
  const idxAt = d => { const i = DATA.dates.findIndex(x => x >= d); return i < 0 ? N - 1 : i; };
  apply(opts.initial);
  if (opts.storageKey) try {
    const saved = JSON.parse(localStorage.getItem(opts.storageKey) || "null");
    if (saved && saved.p === "custom" && saved.from && saved.to) {
      const [a, b] = saved.from <= saved.to ? [saved.from, saved.to] : [saved.to, saved.from];
      if (b >= D0 && a <= D1) apply("custom", idxAt(a), idxAt(b));   /* ignore a range the data has moved past */
    } else if (saved && opts.presets.some(p => p.key === saved.p)) apply(saved.p);
  } catch (e) {}
  sync();
  const fire = () => opts.onChange && opts.onChange({ ...st });
  el.querySelector(".dpbody").addEventListener("click", e => {
    const pr = e.target.closest("[data-p]"), nav = e.target.closest(".dnav"), day = e.target.closest(".dday");
    if (pr) { apply(pr.dataset.p); sync(); fire(); el.open = false; return; }
    if (nav && !nav.disabled) {
      const which = nav.closest(".dcal").dataset.which, v = cal[which];
      const d = new Date(v.y, v.m + +nav.dataset.dir, 1);
      cal[which] = { y: d.getFullYear(), m: d.getMonth() };
      renderCal(which);
      return;
    }
    if (day && !day.disabled) {
      /* move the picked end; if it crosses the other end, carry that one along to keep the span */
      const which = day.closest(".dcal").dataset.which, i = DIDX[day.dataset.d], span = st.r1 - st.r0;
      if (which === "start") apply("custom", i, i <= st.r1 ? st.r1 : i + span);
      else apply("custom", i >= st.r0 ? st.r0 : i - span, i);
      sync(false); fire();
      const again = el.querySelector(`.dcal[data-which="${which}"] .dday[data-d="${DATA.dates[which === "start" ? st.r0 : st.r1]}"]`);
      if (again) again.focus();
    }
  });
  return {
    el,
    get: () => ({ ...st }),
    refresh() { if (st.preset !== "custom") { apply(st.preset); sync(); } },
  };
}

/* ---------- top-level tabs ----------
   Each newer tab's script registers tabHooks[key] = { show(), resize() }: show() runs every time
   the tab opens (build lazily on the first call), resize() when the window width changes while it's open. */
const TABS = [
  { key: "main",   label: "Overview" },
  { key: "states", label: "States in Play" },
  { key: "hpage",  label: "State Page Health" },
  { key: "hall",   label: "Fire Page Health" },
];
const tabHooks = {};
let curTab = "main";
function showTab(key) {
  if (!TABS.some(t => t.key === key)) key = "main";
  curTab = key;
  tip.style.display = "none";
  TABS.forEach(t => {
    document.getElementById("pane-" + t.key).hidden = t.key !== key;
    const b = document.getElementById("tab-" + t.key);
    b.setAttribute("aria-selected", String(t.key === key));
    b.tabIndex = t.key === key ? 0 : -1;
  });
  const nav = document.getElementById("tabs"), sb = document.getElementById("tab-" + key);
  if (nav && sb && nav.scrollWidth > nav.clientWidth) {
    const nr = nav.getBoundingClientRect(), br = sb.getBoundingClientRect();
    if (br.left < nr.left) nav.scrollLeft += br.left - nr.left - 16;
    else if (br.right > nr.right) nav.scrollLeft += br.right - nr.right + 16;
  }
  try { localStorage.setItem("wdo-tab", key); } catch (e) {}
  try { history.replaceState(null, "", "#" + key); } catch (e) {}
  if (key === "main") { if (chartGeom().w !== renderedW) renderAll(); if (quadW() !== renderedQW) renderQuad(DATA.states.map(healthOf)); }
  else if (tabHooks[key] && tabHooks[key].show) tabHooks[key].show();
}
function initTabs() {
  const nav = document.getElementById("tabs");
  nav.innerHTML = TABS.map(t => `<button type="button" role="tab" id="tab-${t.key}" aria-controls="pane-${t.key}"
    aria-selected="false" tabindex="-1">${t.label}</button>`).join("");
  nav.addEventListener("click", e => { const b = e.target.closest("[role=tab]"); if (b) showTab(b.id.slice(4)); });
  nav.addEventListener("keydown", e => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = TABS.findIndex(t => t.key === curTab), j = (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    showTab(TABS[j].key);
    document.getElementById("tab-" + TABS[j].key).focus();
  });
  let start = (location.hash || "").slice(1);
  if (!TABS.some(t => t.key === start)) try { start = localStorage.getItem("wdo-tab") || "main"; } catch (e) { start = "main"; }
  showTab(start);
  addEventListener("hashchange", () => { const k = location.hash.slice(1); if (k !== curTab && TABS.some(t => t.key === k)) showTab(k); });
}

/*__TABS_JS__*/

/* ---------- boot ---------- */
buildControls();
buildCards();
buildOverview();
if (PHONE_Q.addEventListener) PHONE_Q.addEventListener("change", () => { buildOverview(); buildMovers(); buildTopQueries(); });
initMovers();
buildTopQueries();
renderAll();
initTabs();
let resizeRaf = 0;
addEventListener("resize", () => {
  cancelAnimationFrame(resizeRaf);
  resizeRaf = requestAnimationFrame(() => {
    if (curTab === "main") { if (chartGeom().w !== renderedW) renderAll(); if (quadW() !== renderedQW) renderQuad(DATA.states.map(healthOf)); }
    else if (tabHooks[curTab] && tabHooks[curTab].resize) tabHooks[curTab].resize();
  });
});
</script>
"""

def tab_src(ext):
    """the newer tabs' code lives in tabs/*.js and tabs/*.css, inlined here (missing files = empty)"""
    out = []
    only = os.environ.get("DASHBOARD_TABS")   # e.g. "states": test one tab without the other's work in progress
    for name in ("states", "health"):
        if only and name not in only.split(","):
            continue
        p = os.path.join(BASE, "tabs", f"{name}.{ext}")
        if os.path.exists(p):
            with open(p) as f:
                out.append(f.read())
    return "\n".join(out)

html = (HTML.replace("/*__TABS_CSS__*/", tab_src("css")).replace("/*__TABS_JS__*/", tab_src("js"))
        .replace("__DATA__", json.dumps(payload, separators=(",", ":"))).replace("__GENERATED__", generated))
with open(OUT, "w") as f:
    f.write(html)
n_traffic = sum(1 for s in states_payload if s["stats"])
print(f"wrote {OUT} ({len(html)//1024} KB): {len(states_payload)} states "
      f"({n_traffic} with traffic, {len(states_payload)-n_traffic} trends-only)")
