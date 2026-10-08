/* ---------- tab: States in Play — where to look: search demand, visibility and clicks per state ----------
   Two tables over two picked periods; the Comparison table always follows the Top States table's row order. */
(() => {
  const pane = document.getElementById("pane-states");
  const DEM = DATA.demand;
  const END = GSC_LAST != null ? GSC_LAST : N - 2;   /* presets end at Search Console's last complete day */
  const G0 = GSC && GSC.coveredFrom && DIDX[GSC.coveredFrom] != null ? DIDX[GSC.coveredFrom] : 0;
  /* how many of the days r0..r1 Search Console covers */
  const gdays = (r0, r1) => GSC_LAST == null ? 0 : Math.max(0, Math.min(r1, GSC_LAST) - Math.max(r0, G0) + 1);
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const T0 = DEM ? DEM.timeframe.split(" ")[0] : DATA.dates[0];
  const TERMS = ["fires", "wildfires", "fire map", "wildfire map"];
  const NAT_KWS = (DEM && DEM.national && DEM.national.kws) || TERMS;
  const ST_KWS = TERMS.map(t => `<state> ${t}`);
  /* combined daily demand = mean of the area's 4 terms (meanSeries skips missing days) */
  const AREAS = [
    { key: "national", name: "National", abbr: "US", nat: true, dem: DEM && DEM.national ? meanSeries(DEM.national.s) : null, gs: (GSC && GSC.site) || null },
    ...DATA.states.map(st => {
      const d = DEM && DEM.states && DEM.states[st.key];
      return { key: st.key, name: st.name, abbr: st.abbr, dem: d ? meanSeries(d.s) : null, gs: (st.gsc && st.gsc.web) || null };
    }),
  ];
  const AREA = Object.fromEntries(AREAS.map(a => [a.key, a]));
  const COLS = [
    { k: "name", label: "State", short: "State", tip: "Click a row to open Review Health · All Pages for that state" },
    { k: "d", label: "Search Demand", short: "Demand", tip: `Google Trends interest, averaged over the dates (each day = the mean of the 4 terms). National: ${NAT_KWS.join(", ")} (US). State: ${ST_KWS.join(", ")} (searches made in-state). Each state is on its own 0–100 scale (100 = its busiest term-day since ${fdate(T0)}), so compare a state with itself across periods, not with other states. 0 = below Google's reporting threshold on every day; grey italic = reported on fewer than half the days.` },
    { k: "i", label: "Impressions", short: "Impr.", tip: "Search Console impressions (web search), summed over the dates, for all of the state's pages: its state page plus its fire pages. National = the whole site." },
    { k: "ctr", label: "CTR", short: "CTR", tip: "Click-through rate: Traffic from Search ÷ Impressions" },
    { k: "c", label: "Traffic from Search", short: "Traffic", tip: "Search Console clicks (web search), summed over the dates, for the same pages" },
    { k: "pos", label: "Avg Position", short: "Pos.", tip: "Average position in Google results over the dates, weighted by impressions (1 = the top result)" },
  ];
  let sort = { k: "i", dir: -1 }, main, cmp, built = false;
  try {
    const s = JSON.parse(localStorage.getItem("wdo-states-sort") || "null");
    if (s && COLS.some(c => c.k === s.k) && (s.dir === 1 || s.dir === -1)) sort = s;
  } catch (e) {}

  function statsOf(a, r0, r1) {
    let sum = 0, n = 0, nz = 0;
    if (a.dem) for (let i = r0; i <= r1; i++) if (a.dem[i] != null) { sum += a.dem[i]; n++; if (a.dem[i] > 0) nz++; }
    const g = a.gs && r1 >= r0 ? gscWin(a.gs, r1, r1 - r0 + 1) : null;
    return { name: a.name, d: n ? sum / n : null, dn: n, dnz: nz,
             i: g && g.i, c: g && g.c, ctr: g && g.ctr, pos: g && g.pos };
  }
  const statsAll = (r0, r1) => new Map(AREAS.map(a => [a.key, statsOf(a, r0, r1)]));
  /* State sorts A→Z first; numbers biggest first; missing values always last */
  function orderOf(stats) {
    const byName = (x, y) => stats.get(x).name.localeCompare(stats.get(y).name);
    return AREAS.filter(a => !a.nat).map(a => a.key).sort((x, y) => {
      if (sort.k === "name") return sort.dir * byName(x, y);
      const a = stats.get(x)[sort.k], b = stats.get(y)[sort.k];
      if (a == null || b == null) return (a == null) - (b == null) || byName(x, y);
      return sort.dir * (a - b) || byName(x, y);
    });
  }

  const DASH = `<td class="lbl">–</td>`;
  const numCell = v => v == null ? DASH : `<td>${v.toLocaleString()}</td>`;
  function demCell(a, s) {
    if (s.d == null) return `<td class="lbl" title="No Google Trends data for ${a.dem ? "these dates" : "this area"}">–</td>`;
    if (!s.dnz) return `<td class="lbl" title="0 ${s.dn > 1 ? `on all ${s.dn} days` : "that day"}: below Google's reporting threshold">0</td>`;
    const v = s.d < 0.05 ? "&lt;0.1" : s.d.toFixed(1);
    return s.dnz < s.dn / 2
      ? `<td class="lbl sp" title="Google reported these terms on ${s.dnz} of ${s.dn} days; the rest were below its reporting threshold (0)">${v}</td>`
      : `<td>${v}</td>`;
  }
  function tableHtml(top, stats, order, label) {
    const th = c => {
      const on = top && sort.k === c.k;
      /* both tables carry the indicator (hidden unless sorted), so their headers wrap alike */
      const si = pre => `<span class="si ${pre ? "pre" : "post"}${on ? " on" : ""}" aria-hidden="true">${on && sort.dir === 1 ? "▴" : "▾"}</span>`;
      const lbl = `<span class="lf">${c.label}</span><span class="ls">${c.short}</span>`;
      const txt = c.k === "name" ? lbl + si(false) : si(true) + lbl;
      return `<th${c.k === "name" ? ` class="l"` : ""}${on ? ` aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : ""} title="${esc(c.tip)}">${
        top ? `<button type="button" class="sortb" data-k="${c.k}">${txt}</button>` : txt}</th>`;
    };
    const row = key => {
      const a = AREA[key], s = stats.get(key);
      return `<tr class="mrow${a.nat ? " nat" : ""}" data-key="${key}" tabindex="0"${a.nat
          ? ` title="National Google Trends terms (US-wide searches) · Search Console for the whole site"` : ""}>
        <td class="mn"><span class="lf">${esc(a.name)}</span><span class="ls">${esc(a.abbr)}</span></td>${demCell(a, s)}${numCell(s.i)}${s.ctr == null ? DASH : `<td>${(s.ctr * 100).toFixed(1)}%</td>`}${numCell(s.c)}${s.pos == null ? DASH : `<td>${fposn(s.pos)}</td>`}</tr>`;
    };
    return `<table class="mtab sttab" aria-label="${esc(label)}">
      <colgroup>${COLS.map((c, i) => `<col class="c${i}">`).join("")}</colgroup>
      <thead><tr class="grp"><th class="l"></th><th class="gt"><span>Google Trends</span></th><th colspan="4"><span>Search Console</span></th></tr>
      <tr>${COLS.map(th).join("")}</tr></thead>
      <tbody>${row("national")}${order.map(row).join("")}</tbody></table>`;
  }

  const span = (r0, r1) => (r0 === r1 ? fdate(DATA.dates[r0]) : `${fdate(DATA.dates[r0])} – ${fdate(DATA.dates[r1])}`)
    + ` · ${plural(r1 - r0 + 1, "day")}`;
  /* what the dates leave out: Search Console's ~2-day lag, Google Trends' partial last day */
  function lagNote(r0, r1) {
    let t = "";
    if (!GSC || GSC_LAST == null) t += " · no Search Console data";
    else if (r0 > GSC_LAST) t += " · no Search Console days yet (it runs about 2 days behind)";
    else if (r1 > GSC_LAST) t += ` · Search Console through ${fdate(DATA.dates[GSC_LAST])} (${gdays(r0, r1)} of the ${r1 - r0 + 1} days)`;
    if (DEM && r1 === N - 1) t += ` · ${fdate(DATA.dates[N - 1])} partial in Google Trends`;
    return t;
  }
  /* Previous Period's length: the main dates' Search Console days when they run past its last complete
     day (a custom pick), so its totals compare like for like; otherwise the same number of days */
  const prevLen = m => { const g = gdays(m.r0, m.r1); return g && m.r1 > GSC_LAST ? g : m.r1 - m.r0 + 1; };
  function render() {
    tip.style.display = "none";
    const m = main.get(), c = cmp.get(), prev = c.preset === "prev";
    const sm = statsAll(m.r0, m.r1), order = orderOf(sm);
    /* "Previous Period" with nothing before the main dates: show the gap, not overlapping days */
    const none = prev && m.r0 === 0;
    const sc = none ? statsAll(1, 0) : statsAll(c.r0, c.r1);
    pane.querySelector(".st-sub").textContent = span(m.r0, m.r1) + lagNote(m.r0, m.r1)
      + (sort.k === "d" ? " · Search Demand ranks each state on its own scale, not by search volume" : "");
    const gm = gdays(m.r0, m.r1), gc = none ? 0 : gdays(c.r0, c.r1), len = c.r1 - c.r0 + 1;
    pane.querySelector(".st-csub").innerHTML = none ? `No data before ${fdate(DATA.dates[0])} to compare with`
      : esc(span(c.r0, c.r1)
        + (prev && len < prevLen(m) ? ` · data starts ${fdate(DATA.dates[0])}` : "")
        + (prev && len === prevLen(m) && len !== m.r1 - m.r0 + 1 ? " · matches the Search Console days of Top States" : "")
        + lagNote(c.r0, c.r1))
        + (gm && gc && gm !== gc ? ` <span class="stwarn">· Search Console totals here cover ${plural(gc, "day")} vs ${gm} in Top States</span>` : "");
    /* the shared picker can't show an empty range: say so instead of a date the table doesn't use */
    if (none) cmp.el.querySelector(".rplabel").innerHTML = `Previous Period <span class="lbl">· none</span>`;
    pane.querySelector(".st-top").innerHTML = tableHtml(true, sm, order, `Top states, ${span(m.r0, m.r1)}`);
    pane.querySelector(".st-cmp").innerHTML = tableHtml(false, sc, order, `Comparison, ${none ? "no dates" : span(c.r0, c.r1)}`);
    hl(hlKey);
  }

  let hlKey = null;
  /* hovering or focusing a row lights up the same state in the other table */
  function hl(key) {
    hlKey = key;
    pane.querySelectorAll(".sttab tr.mrow").forEach(r => r.classList.toggle("hl", r.dataset.key === key));
  }
  function open(key) {
    if (tabHooks.hall && tabHooks.hall.select) tabHooks.hall.select(key);
    const top = document.getElementById("tabs").getBoundingClientRect().top;
    showTab("hall");
    if (top < 0) scrollBy(0, top);
  }

  function build() {
    const gl = GSC_LAST != null ? fdate(DATA.dates[GSC_LAST]) : null;
    pane.innerHTML = `<div class="tbar"></div>
      <div class="stgrid">
        <section class="panel"><div class="sthead"><h2>Top States</h2></div><div class="psub st-sub"></div><div class="stwrap st-top"></div></section>
        <section class="panel"><div class="sthead"><h2>Comparison</h2></div><div class="psub st-csub"></div><div class="stwrap st-cmp"></div></section>
      </div>
      <div class="stkw">Google Trends terms · <b>National:</b> ${NAT_KWS.map(esc).join(", ")} · <b>State:</b> ${ST_KWS.map(esc).join(", ")} (searches made in-state)${DEM ? ". Each area is on its own 0–100 scale: compare a state with itself across the two tables, not with other states." : " — not available in this build"}</div>
      <div class="tabnotes">
        <p><b>Columns.</b> <b>Search Demand</b> = Google Trends interest in the four terms above, averaged over the dates
        (each day is the mean of the four). <b>Impressions</b> and <b>Traffic from Search</b> = Search Console impressions and
        clicks, summed over the dates. <b>CTR</b> = clicks ÷ impressions. <b>Avg Position</b> = average position in Google
        results, weighted by impressions (1 = the top result). The Comparison table keeps the Top States row order, so the
        two line up row for row.</p>
        <p><b>Search Demand is a relative index, not a search count.</b> Each area's four terms come from one Google Trends
        request and share one 0–100 scale: 100 = that area's busiest term-day since ${fdate(T0)}. A state's number can be
        compared with its own number in another period (the Comparison table), not with other states'. <b>0</b> means
        below Google's reporting threshold on every day — common for these in-state terms in smaller states; a grey
        italic number means Google reported the terms on fewer than half the days. Days when Google Trends returned zeros for
        many areas at once are treated as missing.</p>
        <p><b>Sources and lag.</b> Search Console (Google web search) runs about two days behind, so the date presets end
        at its last complete day${gl ? ` (${gl})` : ""} and every column covers the same complete days; days after that are
        left out of the Search Console columns (Previous Period then spans as many days as Search Console has, so totals
        compare like for like). Google Trends is daily and its latest day is partial. Search Console counts
        all of a state's pages — its state page plus its fire pages; <b>National</b> = the whole site (every page,
        including the homepage) next to the national search terms. Click a row to open Review Health · All Pages for it.</p>
      </div>`;
    const bar = pane.querySelector(".tbar");
    const preset = (key, label, days) => ({ key, label, get: () => [END - days + 1, END] });
    main = makeRangePicker(bar, {
      title: `Presets end at Search Console's last complete day${gl ? ` (${gl})` : ""}; it runs about 2 days behind. Pick any dates on the calendars.`,
      presets: [preset("7", "Last Week", 7), preset("14", "Last 14 Days", 14), preset("30", "Last 30 Days", 30), preset("90", "Last 90 Days", 90)],
      initial: "7", storageKey: "wdo-states-range", minDays: 1,
      onChange: () => { cmp.refresh(); render(); },
    });
    bar.insertAdjacentHTML("beforeend", `<span class="tlabel">${gl ? `Search Console complete through ${gl}` : "No Search Console data"}${
      DEM ? ` · Google Trends through ${fdate(DATA.dates[N - 1])} (partial)` : " · no Google Trends demand data"}</span>`);
    cmp = makeRangePicker(pane.querySelectorAll(".sthead")[1], {
      title: "Dates to compare with. Previous Period = the same number of days just before the Top States dates, and follows them (if those run past Search Console's last complete day: as many days as Search Console has in them).",
      presets: [{ key: "prev", label: "Previous Period", get: () => { const m = main.get(); return [Math.max(0, m.r0 - prevLen(m)), m.r0 - 1]; } }],
      initial: "prev", storageKey: "wdo-states-cmp", minDays: 1,
      onChange: render,
    });
    cmp.el.classList.add("pop-r");   /* the popover opens leftward from the panel's right edge */

    const grid = pane.querySelector(".stgrid");
    grid.addEventListener("click", e => {
      const b = e.target.closest("button.sortb");
      if (b) {
        const k = b.dataset.k;
        sort = sort.k === k ? { k, dir: -sort.dir } : { k, dir: k === "name" ? 1 : -1 };
        try { localStorage.setItem("wdo-states-sort", JSON.stringify(sort)); } catch (err) {}
        render();
        pane.querySelector(`button.sortb[data-k="${k}"]`).focus();
        return;
      }
      const tr = e.target.closest("tr.mrow");
      if (tr) open(tr.dataset.key);
    });
    grid.addEventListener("keydown", e => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr.mrow")) { e.preventDefault(); open(e.target.dataset.key); }
    });
    grid.addEventListener("pointerover", e => {
      const tr = e.target.closest(".sttab tr.mrow"), k = tr ? tr.dataset.key : null;
      if (k !== hlKey) hl(k);
    });
    grid.addEventListener("pointerleave", () => hl(null));
    grid.addEventListener("focusin", e => { if (e.target.matches("tr.mrow")) hl(e.target.dataset.key); });
    grid.addEventListener("focusout", e => { if (e.target.matches("tr.mrow")) hl(null); });
    render();
    built = true;
  }

  tabHooks.states = {
    show() { if (!built) build(); },
    resize() {},   /* tables reflow on their own */
  };
})();
