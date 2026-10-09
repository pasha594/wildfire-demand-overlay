/* ---------- State Page Health and Fire Page Health tabs ----------
   One implementation, two scopes for Search Console: "page" = a state's own page (national: the
   homepage), "fire" = the state's fire pages only, not its state page (national: every fire page, no
   state pages or homepage). Search demand is the same in both: Google Trends, the mean of the area's
   four terms each day (meanSeries). */
(() => {
/* every chart keeps the right-axis margin, so all eight share one x scale (and one set of date ticks);
   HMT leaves room above the plot for the axis titles */
const HML = 40, HMR = 44, HMT = 24, HMB = 24;
/* capture and share (the right-hand log charts) are measured only over a week with at least CAP_DAYS days
   Google reported searches, a Google Trends signal (the four terms' raw values added up) of CAP_SIG, and
   enough of the numerator: CAP_X impressions or clicks. Below that, 1-point rounding, the reporting
   threshold and a handful of clicks dominate. An area needs CAP_MIN measurable days in its history for a
   typical rate. CTR needs CTR_MIN impressions in its week for a stable %. The log axis never runs past
   2^LOG_LO–2^LOG_HI (⅛×–32×); values beyond are drawn at the edge. */
const CAP_DAYS = 4, CAP_SIG = 10, CAP_MIN = 14, CTR_MIN = 50, LOG_LO = -3, LOG_HI = 5;
const CAP_X = { impressions: 50, clicks: 10 };
const PRESETS = [
  { key: "30",  label: "Last 30 days",  get: () => [N - 30, N - 1] },
  { key: "90",  label: "Last 90 days",  get: () => [N - 90, N - 1] },
  { key: "180", label: "Last 180 days", get: () => [N - 180, N - 1] },
  { key: "all", label: "All data",      get: () => [0, N - 1] },
];
/* each section: the question, then one sentence on how to read it (the rest lives in "About this data") */
const ROWS = [
  { q: "Are we capturing search demand?",
    sub: "1× means Google showed our pages as often as usual for this much searching; below 1× points to a ranking or indexing gap." },
  { q: "Is demand turning into traffic?",
    sub: "1× means as many clicks as usual for this much searching; below 1× means less of that demand is reaching us." },
  { q: "Are impressions turning into traffic?",
    sub: "If click-through rate (CTR) falls while impressions hold, look at titles, snippets or position." },
  { q: "Are we winning the searches we track?", track: true },   /* subtitle depends on the area (renderTracked) */
];
const CH = [
  { t: "Search demand and impressions" },
  { t: "Impressions vs demand", sub: "7-day rate vs our typical (1×), log scale" },
  { t: "Search demand and search traffic" },
  { t: "Traffic vs demand", sub: "7-day rate vs our typical (1×), log scale" },
  { t: "Impressions and search traffic" },
  { t: "CTR", sub: "Clicks ÷ impressions, 7-day rolling" },
  { t: "Search demand and our impressions on these searches" },
  { t: "Share of these searches we're shown in", tl: "Our share of these searches", sub: "7-day share vs our typical (1×), log scale" },
];
const tickFmt = v => v >= 1e6 ? +(v / 1e6).toFixed(2) + "M" : v >= 1000 ? +(v / 1000).toFixed(2) + "k" : String(+v.toFixed(2));
const num = v => v == null ? "–" : v < 10 && v % 1 ? v.toFixed(1) : Math.round(v).toLocaleString();
const rfmt = v => v == null ? "–" : v >= 100 ? Math.round(v).toLocaleString() : v >= 1 ? v.toFixed(1) : v.toFixed(2);
const dfmt = v => v == null ? "–" : v.toFixed(1);
/* compact counts for the biggest-searches line: 16.5k, 101k, 1.2M */
const kfmt = v => v >= 1e6 ? +(v / 1e6).toFixed(1) + "M" : v >= 1e5 ? Math.round(v / 1000) + "k" : v >= 1000 ? +(v / 1000).toFixed(1) + "k" : String(v);
/* a capture multiple, two significant digits ("0.72×", "1.3×", "12×"); under 0.1× without a trailing
   zero ("0.007×", not "0.0070×"); axis ticks are powers of two */
const cfmt = v => v == null ? "–" : (v >= 10 ? Math.round(v).toLocaleString() : v >= 0.1 ? v.toPrecision(2)
  : v >= 0.001 ? String(+v.toPrecision(2)) : "<0.001") + "×";
/* axis tick for 2^m: "⅛×" "¼×" "½×" "1×" "2×" "4×" … (the axis never goes below ⅛×); the fraction
   glyphs are drawn a size up so they read as large as the digits beside them */
const FRAC = { "-1": "½", "-2": "¼", "-3": "⅛" };
const xfmt = m => (m < 0 ? `<tspan font-size="13.5">${FRAC[m]}</tspan>` : String(Math.pow(2, m))) + "×";
const keyOf = l => l.fill ? legendSwatch("traffic") : legendSwatch({ color: l.color });   /* legend / tooltip key mirrors the mark */
const sw = l => `<span class="sw">${keyOf(l)}</span>`;
/* day i of the axis as a date: works past either end (weeks that start before the data or end after it) */
const dayAt = i => { const [y, m, d] = DATA.dates[0].split("-"); return new Date(+y, m - 1, +d + i); };
const dlab = i => dayAt(i).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const niceUp = (raw, min = 0) => {
  if (!(raw > min)) return min || 1;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  return [1, 2, 2.5, 5, 10].map(m => m * p).find(s => s >= raw - 1e-9);
};
const boxH = w => w < 480 ? 200 : 240;
const gscLast = () => GSC_LAST == null ? N - 1 : GSC_LAST;
/* the Google Trends signal on day j: the four terms' raw values (the integers Google returned) added up */
const sigOf = (a, j) => a.terms.reduce((p, t) => p + (t[j] || 0), 0);

/* capture of search demand, for one numerator x (impressions or clicks) needing at least minX of it in a
   week. For each day d, the usable days among d-6..d are those Google reported searches (demand above
   zero: a zero means "below its threshold", not "no demand") and x has a value; over them rate
   r = Σx ÷ Σdemand, measured only with at least CAP_DAYS such days, a Trends signal of CAP_SIG and
   Σx >= minX. The typical rate R is the median r over every measurable day of the area's history through
   Search Console's last complete day — independent of the picked dates — and c = r ÷ R (1 = typical).
   Days after that last day get nothing: the window would only be shedding older days. Google Trends
   rescales its 0–100 index, so r on its own means little. k0 counts the days the Trends rule alone
   passes (sig), to tell "too little Trends signal" from "too few impressions/clicks". tx / nx = x over
   every day of the window that has it (usable or not), so a readout can show the week's real total. */
function capture7(x, a, minX) {
  const D = a.D, last = gscLast();
  let k0 = 0;
  const w = DATA.dates.map((_, d) => {
    if (d > last) return null;
    let sx = 0, sd = 0, p = 0, n = 0, tx = 0, nx = 0, dn = 0;
    for (let j = Math.max(0, d - 6); j <= d; j++) {
      if (x[j] == null) continue;
      tx += x[j]; nx++;
      if (D[j] == null) dn++;
      if (!(D[j] > 0)) continue;
      sx += x[j]; sd += D[j]; p += sigOf(a, j); n++;
    }
    const sig = n >= CAP_DAYS && p >= CAP_SIG;
    if (sig) k0++;
    return { sx, sd, p, n, tx, nx, dn, sig, r: sig && sx >= minX ? sx / sd : null };
  });
  const rs = w.filter(o => o && o.r != null).map(o => o.r).sort((u, v) => u - v), k = rs.length, h = k >> 1;
  const R = k >= CAP_MIN ? (k % 2 ? rs[h] : (rs[h - 1] + rs[h]) / 2) : null;   /* > 0: every r has Σx >= minX */
  w.forEach(o => { if (o) o.c = o.r != null && R ? o.r / R : null; });
  return { w, R, k, k0, minX };
}

/* trailing 7-day CTR: Σclicks ÷ Σimpressions over the days d-6..d with both; nothing under 4 such days
   or after Search Console's last complete day, and v = null when the week has fewer than CTR_MIN
   impressions (too few for a stable %) */
function ctr7(gs) {
  const last = gscLast();
  return DATA.dates.map((_, d) => {
    if (d > last) return null;
    let a = 0, b = 0, n = 0;
    for (let j = Math.max(0, d - 6); j <= d; j++) if (gs.c[j] != null && gs.i[j] != null) { a += gs.c[j]; b += gs.i[j]; n++; }
    return n >= 4 ? { a, b, n, v: b >= CTR_MIN ? a / b : null } : null;
  });
}

/* log2 axis for the capture charts. The domain is the plotted values' own extent (a little headroom past
   them), widened to at least ½×–2× and capped at ⅛×–32× — values beyond the cap are drawn at the edge.
   Ticks are the powers of two inside it, thinned to every other (or third…) when closer than ~20px;
   1× always stays. */
function log2Axis(lines, r0, r1, ih) {
  let lo = 0, hi = 0;
  lines.forEach(l => { for (let i = r0; i <= r1; i++) { const v = l.s[i];
    if (v > 0) { const e = Math.log2(v); if (e < lo) lo = e; if (e > hi) hi = e; } } });
  const pad = 0.04 * (Math.max(hi, 1) - Math.min(lo, -1));
  const a = Math.max(LOG_LO, Math.min(-1, lo - pad)), b = Math.min(LOG_HI, Math.max(1, hi + pad));
  let e = 1;
  while (ih / (b - a) * e < 20) e++;
  const ticks = [];
  for (let m = Math.ceil(a - 1e-9); m <= Math.floor(b + 1e-9); m++) if (m % e === 0) ticks.push({ v: Math.pow(2, m), m, one: m === 0 });
  const at = v => Math.min(b, Math.max(a, Math.log2(v)));
  return { ticks, Y: v => HMT + ih - (at(v) - a) / (b - a) * ih };
}

function areaData(scope, key) {
  const st = key === "national" ? null : DATA.states.find(s => s.key === key) || null;
  const dm = DATA.demand ? (st ? DATA.demand.states[st.key] : DATA.demand.national) : null;
  /* "page": the state page (national: the homepage); "fire": the state's fire pages (national: every fire page) */
  const gs = !GSC ? null : scope === "page" ? (st ? st.gscPage : GSC.home) : (st ? st.gscFire : GSC.fireNational);
  const trk = !GSC ? null : (st ? st.gscTracked : GSC.trackedNational) || null;
  const pg = scope === "page";
  return {
    st, scope, name: st ? st.name : "the US", hasDm: !!dm, kws: dm ? dm.kws : null, terms: dm ? dm.s : null,
    D: dm ? meanSeries(dm.s) : null, gs: gs || null,
    trk, ts: trk && trk[scope] || null,   /* tracked searches: the area's terms, and this scope's numbers */
    geo: st ? `searches made in ${st.name} (geo US-${st.abbr})` : "searches across the US (geo US)",
    searches: st ? `searches made in ${st.name}` : "searches across the US",
    covers: pg ? (st ? `only the ${st.name} state page (fires.cornea.is/state/${st.key})` : "only the fires.cornea.is homepage")
      : (st ? `only ${st.name}'s fire pages (fires.cornea.is/fire/${st.key}_…), not its state page`
        : "every fire page on fires.cornea.is (no state pages or homepage)"),
    short: pg ? (st ? `the ${st.name} state page` : "the homepage") : (st ? `${st.name}'s fire pages` : "our fire pages"),
    where: pg ? (st ? `the ${st.name} state page` : "the homepage") : (st ? `one of ${st.name}'s fire pages` : "any fire page"),
  };
}

/* one SVG chart into `box`: lines on a left axis (which owns the gridlines) and optionally a right
   axis that reuses those gridlines with its own nice step. o.log puts the left axis on a log2 scale
   (capture multiples) with the 1× line drawn heavier and marked "typical". o.tl / o.tr title the
   left / right axis above its tick labels (tick labels are muted, so the titles say which scale is
   whose). Returns what the hover layer needs. */
function plot(box, o) {
  const { r0, r1, lines } = o;
  const w = Math.max(260, Math.round(box.clientWidth)), h = boxH(w);
  const hasR = lines.some(l => l.ax === "r");
  const mr = HMR, iw = w - HML - mr, ih = h - HMT - HMB;
  const X = i => HML + (i - r0) / (r1 - r0) * iw;
  /* every label wears a paper halo and is drawn after the lines (tx), so no line or hover dot cuts through it */
  const tk = `class="halo" font-size="11.5" fill="var(--muted)"`;
  const ttl = `class="halo" font-size="11" font-weight="600" fill="var(--muted)"`;
  let g = "", tx = "", Yl, Yr;
  if (o.tl) tx += `<text x="0" y="11" ${ttl}>${o.tl}</text>`;
  if (o.tr) tx += `<text x="${w}" y="11" text-anchor="end" ${ttl}>${o.tr}</text>`;
  if (o.log) {
    const A = log2Axis(lines, r0, r1, ih);
    Yl = A.Y;
    let one = "";
    A.ticks.forEach(t => {
      const y = Yl(t.v).toFixed(1), ln = `<line x1="${HML}" x2="${w - mr}" y1="${y}" y2="${y}"`;
      tx += `<text x="${HML - 6}" y="${(+y + 4).toFixed(1)}" text-anchor="end" ${t.one ? `class="halo" font-size="11.5" font-weight="600" fill="var(--ink-2)"` : tk}>${xfmt(t.m)}</text>`;
      if (!t.one) { g += `${ln} stroke="var(--grid)" stroke-width="1"/>`; return; }
      /* 1× (typical) sits over the other gridlines and under the data, heavier than a gridline */
      one = `${ln} stroke="var(--axis)" stroke-width="1.5"/>`;
      tx += `<text x="${w - mr + 6}" y="${(+y + 4).toFixed(1)}" class="halo" font-size="11" fill="var(--ink-2)">typical</text>`;
    });
    g += one;
  } else {
    const top = ax => { let m = 0; lines.forEach(l => { if (l.ax === ax) for (let i = r0; i <= r1; i++) if (l.s[i] > m) m = l.s[i]; }); return m; };
    const tl = top("l"), tr = top("r");
    const L = niceAxis(tl), nGrid = Math.round(L.ymax / L.step);
    const rStep = hasR ? niceUp(tr / nGrid, 1) : 1;
    const fmtL = o.fmtL || tickFmt;
    Yl = v => HMT + ih - v / L.ymax * ih; Yr = v => HMT + ih - v / (rStep * nGrid) * ih;
    for (let k = 0; k <= nGrid; k++) {
      const y = Yl(k * L.step);
      g += `<line x1="${HML}" x2="${w - mr}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(${k ? "--grid" : "--axis"})" stroke-width="1"/>`;
      /* a series that never leaves zero gets only its 0 label: the rest of the scale would be invented */
      if (!k || tl > 0) tx += `<text x="${HML - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end" ${tk}>${fmtL(k * L.step)}</text>`;
      if (hasR && (!k || tr > 0)) tx += `<text x="${w - mr + 6}" y="${(y + 4).toFixed(1)}" ${tk}>${tickFmt(k * rStep)}</text>`;
    }
  }
  const Yof = l => l.ax === "r" ? Yr : Yl;
  let lastR = -1e9;
  xTicks(r0, r1, iw).forEach(([i, t, anchor]) => {
    const tw = t.length * 6.3;
    let x = X(i);
    if (anchor === "middle") x = Math.min(w - mr - tw / 2 + 4, Math.max(HML + tw / 2 - 4, x));
    const left = anchor === "start" ? x : x - tw / 2;
    if (left < lastR + 8) return;      /* never let two labels touch */
    lastR = left + tw;
    tx += `<text x="${x.toFixed(1)}" y="${h - 6}" text-anchor="${anchor}" ${tk}>${t}</text>`;
  });
  /* contiguous runs of days with a value: null breaks the line (no interpolation across gaps) */
  const runs = s => { const out = []; let cur = null;
    for (let i = r0; i <= r1; i++) { if (s[i] == null) { cur = null; continue; } if (!cur) out.push(cur = []); cur.push(i); }
    return out; };
  const base = (HMT + ih).toFixed(1);
  lines.forEach(l => {   /* fills first (traffic wears the dashboard's green wash), then every stroke on top */
    if (!l.fill) return;
    const Y = Yof(l), pt = i => X(i).toFixed(1) + " " + Y(l.s[i]).toFixed(1);
    g += `<path d="${runs(l.s).filter(r => r.length > 1).map(r => `M${X(r[0]).toFixed(1)} ${base}L${r.map(pt).join("L")}L${X(r[r.length - 1]).toFixed(1)} ${base}Z`).join("")}" fill="${l.fill}"/>`;
  });
  lines.forEach(l => {
    const s = l.s, Y = Yof(l), pt = i => X(i).toFixed(1) + " " + Y(s[i]).toFixed(1), rs = runs(s);
    /* a day with no neighbours has no segment: draw it as a dot */
    rs.filter(r => r.length === 1).forEach(([i]) => { g += `<circle cx="${X(i).toFixed(1)}" cy="${Y(s[i]).toFixed(1)}" r="2.2" fill="${l.color}"/>`; });
    const d = rs.filter(r => r.length > 1).map(r => "M" + r.map(pt).join("L")).join("");
    if (d) g += `<path d="${d}" fill="none" stroke="${l.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  });
  g += tx + `<line class="xh" x1="-10" x2="-10" y1="${HMT}" y2="${HMT + ih}" stroke="var(--ink-2)" stroke-width="1" stroke-dasharray="3 3" opacity="0"/><g class="hd"></g>`;
  box.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">${g}</svg>`;
  const svg = box.firstElementChild, xh = svg.querySelector(".xh"), hd = svg.querySelector(".hd");
  return {
    w, x: X, tip: o.tip,
    idx(cx) {
      const r = svg.getBoundingClientRect(), fx = (cx - r.left) / r.width * w;
      if (fx < HML - 8 || fx > w - mr + 8) return null;
      return Math.max(r0, Math.min(r1, Math.round(r0 + (fx - HML) / iw * (r1 - r0))));
    },
    mark(i) {
      if (i == null) { xh.setAttribute("opacity", "0"); hd.innerHTML = ""; return; }
      const x = X(i).toFixed(1);
      xh.setAttribute("x1", x); xh.setAttribute("x2", x); xh.setAttribute("opacity", "0.7");
      hd.innerHTML = lines.map(l => l.s[i] == null ? "" :
        `<circle cx="${x}" cy="${Yof(l)(l.s[i]).toFixed(1)}" r="4" fill="${l.color}" stroke="var(--surface)" stroke-width="2"/>`).join("");
    },
  };
}

function makeHealthTab(key, scope) {
  const pane = document.getElementById("pane-" + key), skey = `wdo-${key}-state`;
  const natLabel = scope === "page" ? "National (homepage)" : "National (all fire pages)";
  const valid = k => k === "national" || DATA.states.some(s => s.key === k);
  let built = false, picker, sel, live, smoothOn = false, area = "national", charts = [], cells = [], hoverI = null, hov = null, lastW = 0;
  try { const s = localStorage.getItem(skey); if (valid(s)) area = s; } catch (e) {}

  function place(cx, cy) {
    let tx = cx + 14, ty = cy + 12;
    if (tx + tip.offsetWidth > innerWidth - 8) tx = cx - tip.offsetWidth - 14;
    if (ty + tip.offsetHeight > innerHeight - 8) ty = cy - tip.offsetHeight - 12;
    tip.style.left = Math.max(8, tx) + "px"; tip.style.top = Math.max(8, ty) + "px";
  }
  /* hov keeps the readout's anchor relative to its chart, so a focused chart's readout follows a scroll */
  function hover(i, ci, cx, cy) {
    hoverI = i;
    charts.forEach(c => c && c.mark(i));
    if (i == null || !charts[ci]) { tip.style.display = "none"; tip.classList.remove("htip"); hov = null; return; }
    const r = cells[ci].getBoundingClientRect();
    hov = { ci, dx: cx - r.left, dy: cy - r.top };
    tip.innerHTML = charts[ci].tip(i);
    tip.classList.add("htip");   /* keeps an 8px gutter on both sides of a phone screen (health.css) */
    tip.style.display = "block";
    place(cx, cy);
  }

  function build() {
    built = true;
    pane.innerHTML = `<div class="tbar">
        <select class="statef" aria-label="Area"><option value="national">${natLabel}</option>` +
        DATA.states.map(s => `<option value="${s.key}">${esc(s.name)}</option>`).join("") + `</select>
        <label class="smooth"><input type="checkbox"> 7-day smoothing</label>
        <p class="tlabel hscope"></p></div>` +
      ROWS.map((r, ri) => `<section class="panel hrow${r.track ? " htrack" : ""}"><h2>${r.q}</h2><div class="psub">${r.sub || ""}</div><div class="hgrid">` +
        [0, 1].map(k => { const c = CH[ri * 2 + k]; return `<div class="hc"><div class="hch"><h3>${c.t}</h3>
          <div class="${c.sub ? "hsub" : "hlg"}">${c.sub || ""}</div></div>
          <div class="hbox" role="group" aria-roledescription="chart"></div><div class="hnote"></div></div>`; }).join("") +
        `</div>${r.track ? `<div class="htrk"></div>` : ""}</section>`).join("") +
      `<section class="panel hweek"><h2>Week by week</h2><div class="psub hwsub"></div>
        <div class="hhint">Swipe sideways for every column.</div><div class="htw"></div></section>
      <div class="tabnotes hnotes"></div><div class="hsr" aria-live="polite"></div>`;
    const bar = pane.querySelector(".tbar");
    /* the bar's height while it's pinned (wide screens), so a focused chart or control scrolls clear of it (health.css) */
    const pinH = () => pane.style.setProperty("--tbar-h", (getComputedStyle(bar).position === "sticky" ? bar.offsetHeight : 0) + "px");
    if (window.ResizeObserver) new ResizeObserver(pinH).observe(bar, { box: "border-box" });
    picker = makeRangePicker(bar, { title: "Dates for every chart and the table on this tab", presets: PRESETS, initial: "90",
      storageKey: `wdo-${key}-range`, minDays: 7, onChange: render });
    bar.prepend(picker.el);
    sel = bar.querySelector("select");
    sel.value = area;
    sel.addEventListener("change", () => { area = sel.value; try { localStorage.setItem(skey, area); } catch (e) {} render(); });
    bar.querySelector(".smooth input").addEventListener("change", e => { smoothOn = e.target.checked; render(); });
    live = pane.querySelector(".hsr");
    cells = [...pane.querySelectorAll(".hbox")];
    document.addEventListener("pointerdown", e => { if (hoverI != null && !cells.some(c => c.contains(e.target))) hover(null); });
    addEventListener("scroll", () => {
      if (hoverI == null) return;
      if (!hov || !cells.includes(document.activeElement)) return hover(null);
      const r = cells[hov.ci].getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) return hover(null);
      place(r.left + hov.dx, r.top + hov.dy);
    }, { passive: true });
    cells.forEach((box, ci) => {
      const move = e => { const c = charts[ci], i = c ? c.idx(e.clientX) : null; i == null ? hover(null) : hover(i, ci, e.clientX, e.clientY); };
      box.addEventListener("pointermove", move);
      box.addEventListener("pointerdown", move);
      box.addEventListener("pointerleave", e => { if (e.pointerType !== "touch") hover(null); });   /* a tap keeps its readout */
      box.addEventListener("blur", () => hover(null));
      box.addEventListener("keydown", e => {
        const c = charts[ci], step = { ArrowLeft: -1, ArrowRight: 1, Home: -1e9, End: 1e9 }[e.key];
        if (e.key === "Escape") return hover(null);
        if (!c || step == null) return;
        e.preventDefault();
        const { r0, r1 } = picker.get(), i = Math.max(r0, Math.min(r1, (hoverI == null ? r1 + (step < 0 ? 1 : 0) : hoverI) + step));
        const r = box.getBoundingClientRect();
        hover(i, ci, r.left + c.x(i) / c.w * r.width, r.top + 24);
        live.textContent = [...tip.querySelectorAll(".d, tr, .tnote")]   /* the readout, for screen readers */
          .map(el => [...el.childNodes].map(n => n.textContent.trim()).filter(Boolean).join(" ")).filter(Boolean).join(". ");
      });
    });
  }

  function render() {
    hover(null);
    const { r0, r1 } = picker.get(), n = r1 - r0 + 1;
    const a = areaData(scope, area), D = a.D, gs = a.gs;
    const sm = s => smoothOn ? smooth7n(s) : s;
    const any = s => !!s && s.slice(r0, r1 + 1).some(v => v != null);
    const tAny = a.ts && a.ts.any;   /* tracked searches, "any of the four" */
    const hasD = any(D), hasG = !!gs && any(gs.i), hasT = !!tAny && any(tAny.i);
    let zero = 0, miss = 0;
    for (let i = r0; i <= r1; i++) { if (!D || D[i] == null) miss++; else if (!D[i]) zero++; }
    const sparse = hasD && zero + miss > n / 2;
    /* a state's fire-page phrase ends in an aside ("…, not its state page"), closed by a comma here */
    pane.querySelector(".hscope").textContent = `Comparing ${a.covers}${a.st && scope === "fire" ? "," : ""} with ${a.searches}` +
      (GSC ? `, using Search Console data through ${fdate(GSC.lastComplete)}.` : ".");
    /* capture over the area's whole history (its typical rate doesn't depend on the picked dates) */
    const capI = D && gs ? capture7(gs.i, a, CAP_X.impressions) : null, capC = D && gs ? capture7(gs.c, a, CAP_X.clicks) : null;
    const capT = D && tAny ? capture7(tAny.i, a, CAP_X.impressions) : null;
    renderTable(a, r0, r1, capI && capI.R);
    renderTracked(a, r0, r1);
    renderNotes(a);

    const noD = a.hasDm ? `Google Trends has no values for ${a.name} in these dates.` : `No Google Trends data for ${a.name}.`;
    /* why a Search Console series has nothing to draw in these dates */
    const gWhy = (s, what) => {
      if (!GSC) return "No Search Console data in this build.";
      let e = -1;
      if (s) for (let i = N - 1; i >= 0; i--) if (s[i] != null) { e = i; break; }
      return e < 0 ? `No Search Console data ${what}.`
        : e < r0 ? `Search Console data ${what} runs through ${fdate(DATA.dates[e])}, before these dates.`
        : `No Search Console data ${what} in these dates.`;
    };
    const noG = gWhy(gs && gs.i, `for ${a.short}`), noT = gWhy(tAny && tAny.i, `on these searches for ${a.short}`);
    const G = { has: hasG, why: noG, i: gs && gs.i }, GT = { has: hasT, why: noT, i: tAny && tAny.i };
    const empty = (ci, msg) => {
      cells[ci].innerHTML = `<div class="hempty" style="--hh:${boxH(Math.max(260, cells[ci].clientWidth))}px">${msg}</div>`;
      cells[ci].setAttribute("aria-label", msg);
      cells[ci].tabIndex = -1;
      charts[ci] = null;
    };
    /* swatch + name; which axis is whose is said by the axis titles in the chart */
    const legend = (ci, lines) => {
      cells[ci].parentNode.querySelector(".hlg").innerHTML = lines.map(l => `<span>${keyOf(l)}${l.name}</span>`).join("");
    };
    const notes = [...pane.querySelectorAll(".hnote")];
    notes.forEach(el => el.textContent = "");
    const label = (ci, t) => {
      cells[ci].setAttribute("aria-label", `${t} for ${a.name}, ${dlab(r0)} – ${dlab(r1)}. Arrow keys step through the days.`);
      cells[ci].tabIndex = 0;
    };
    const sparseNote = `Google Trends reports zero for these terms in ${a.name} on ${zero} of ${n} days${miss ? `, and no value on ${miss} more` : ""}. `
      + `Searching stayed below its reporting threshold, so a flat line means too few searches to report.`;

    /* left-hand chart: two series, each on its own axis (smoothed when 7-day smoothing is on); src = the
       Search Console series it draws (for "nothing to draw" and "not in yet") */
    const dual = (ci, defs, withD, src) => {
      const lines = defs.filter(Boolean).map(d => ({ ...d, s: sm(d.raw) }));
      if (lines.length === 1) lines[0].ax = "l";
      legend(ci, lines);
      const why = [withD && !hasD ? noD : "", src.has ? "" : src.why].filter(Boolean).join(" ");
      if (!lines.length) return empty(ci, why);
      notes[ci].textContent = [why, withD && sparse ? sparseNote : ""].filter(Boolean).join(" ");
      label(ci, CH[ci].t);
      const axT = ax => lines.length > 1 && (lines.find(l => l.ax === ax) || {}).axis;
      charts[ci] = plot(cells[ci], { r0, r1, lines, fmtL: tickFmt, tl: axT("l"), tr: axT("r"), tip: i => {
        const hasDem = lines.some(l => l.kind === "d"), hasGsc = lines.some(l => l.kind === "g");
        const f = (l, v) => l.kind === "d" ? dfmt(v) : num(v);
        const rows = lines.map(l => `<tr><td class="n">${sw(l)}${l.name}</td><td>${f(l, l.s[i])}</td>` +
          (smoothOn ? `<td class="zero">${f(l, l.raw[i])}</td>` : "") + `</tr>`).join("");
        const tn = [];
        if (hasGsc && src.i[i] == null) tn.push(GSC_LAST != null && i > GSC_LAST ? "Search Console: not in yet (~2-day lag)" : "Search Console: no data this day");
        if (hasDem && a.terms) tn.push(D[i] == null ? "Google Trends: no value this day"
          : "Google Trends this day: " + a.kws.map((k, j) => `${esc(k)} ${a.terms[j][i] == null ? "–" : a.terms[j][i]}`).join(", ") + (i === N - 1 ? " (partial day)" : ""));
        return `<div class="d">${fdateY(DATA.dates[i])}</div><table class="tt">` +
          (smoothOn ? `<thead><tr><th></th><th>7-day avg</th><th>Day</th></tr></thead>` : "") + `<tbody>${rows}</tbody></table>` +
          tn.map(t => `<div class="tnote">${t}</div>`).join("");
      } });
    };
    /* "Sep 14 – Sep 20"; just the date when the window is one day (the data's first) */
    const span7 = i => i ? `${dlab(Math.max(0, i - 6))} – ${dlab(i)}` : dlab(i);
    const head7 = i => `<div class="d">${fdateY(DATA.dates[i])}<span class="lbl">week ending here</span></div>`;
    const wk7 = (i, n) => `${span7(i)}: ${n} of 7 days`;
    const notIn = `<div class="tnote">Search Console not in yet (~2-day lag)</div>`;
    const lastG = Math.min(r1, gscLast());
    const f0 = D ? Math.max(0, D.findIndex(v => v != null)) : 0;
    const since = fdate(DATA.dates[f0]), nDays = k => `${k} day${k === 1 ? "" : "s"}`;
    /* capture / share chart (rows 1, 2 and 4, right): the week's rate as a multiple of the area's typical
       rate, log scale; weeks with too thin a signal are gaps. c = { nm: the numerator in words, src, noun:
       "capture" | "share", gauge: a sentence added when Google Trends is too thin for a typical } */
    const capture = (ci, K, c) => {
      if (!hasD) return empty(ci, noD);
      if (!c.src.has) return empty(ci, c.src.why);
      if (!K.R) return empty(ci, K.k0 >= CAP_MIN
        ? `Too few ${c.nm} for ${a.short} to measure ${c.noun}: a week needs ${K.minX}+, and only ${nDays(K.k)} since ${since} had that with enough Google Trends signal (a typical needs ${CAP_MIN}).`
        : `${trendsThin} ${c.noun} (only ${nDays(K.k0)} since ${since} had enough signal; a typical needs ${CAP_MIN}).${c.gauge ? " " + c.gauge : ""}`);
      const s = K.w.map(x => x && x.c);
      if (!s.slice(r0, r1 + 1).some(v => v != null))   /* say which side is thin in these dates */
        return empty(ci, K.w.slice(r0, lastG + 1).some(x => x && x.sig)
          ? `Too few ${c.nm} to measure ${c.noun} in these dates: no week with enough Google Trends signal had ${K.minX}+.`
          : `Google Trends reports zero or too little for these terms in ${a.name} in every week of these dates, so ${c.noun} can't be measured here.`);
      /* the first 6 days can't fill a 7-day window: not worth a note on their own */
      if (K.w.slice(Math.max(r0, 6), lastG + 1).some(x => x && x.c == null))
        notes[ci].textContent = `Gaps are weeks too thin to measure: Google Trends above zero on under ${CAP_DAYS} days, a Trends signal under ${CAP_SIG}, or under ${K.minX} ${c.nm}.`;
      label(ci, CH[ci].t);
      const o = { color: "var(--ink-2)" }, Nm = c.nm[0].toUpperCase() + c.nm.slice(1);
      const need = k => ` <span class="u">(needs ${k}+)</span>`;
      const row = (nm, v) => `<tr><td class="n">${nm}</td><td>${v}</td></tr>`;
      charts[ci] = plot(cells[ci], { r0, r1, log: true, lines: [{ s, color: o.color, ax: "l" }], tip: i => {
        const x = K.w[i];
        if (!x) return head7(i) + notIn;
        const ok = x.c != null, off = ok && (x.c > Math.pow(2, LOG_HI) || x.c < Math.pow(2, LOG_LO));
        /* why it isn't measurable, naming the side that's thin: with under CAP_DAYS days of data that is
           (nearly always) Google Trends at zero, whatever the impressions or clicks were */
        const thin = x.n < CAP_DAYS
          ? (x.nx < CAP_DAYS ? `Search Console has only ${x.nx} of these days`
            : x.n ? `Google Trends was above zero on only ${x.n} of ${x.nx} days`
            : `Google Trends was ${x.dn ? "zero or missing" : "zero"} all week`)
          : [x.p < CAP_SIG && "too little Google Trends signal",
             x.sx < K.minX && (x.tx > x.sx ? `too few ${c.nm} on the days Google Trends was above zero` : `too few ${c.nm}`)].filter(Boolean).join(", ");
        const start = i < 6 && `the data starts ${fdateY(DATA.dates[0])}, so this week has only ${i + 1} of its 7 days`;
        /* the numerator over the whole window (what the left chart and the table show); when some of its
           days had no Google Trends signal, also the part the rate uses, which is what needs minX */
        const xr = x.n && x.sx !== x.tx
          ? [row(`${Nm}, 7 days`, num(x.tx)), row(`On the ${nDays(x.n)} with data`, num(x.sx) + need(K.minX))]
          : [row(`${Nm}, 7 days`, num(x.tx) + (x.n ? need(K.minX) : ""))];
        const rows = [row(sw(o) + (CH[ci].tl || CH[ci].t), ok ? `${cfmt(x.c)} <span class="u">typical${off ? ", off the chart" : ""}</span>` : "–"),
          ...xr,
          row("Search demand, 7 days", dfmt(x.sd)),
          row("Google Trends signal", x.p.toLocaleString() + need(CAP_SIG)),
          row("Days with data", `${x.n} of 7` + (x.n < CAP_DAYS ? need(CAP_DAYS) : ""))];
        return head7(i) + `<table class="tt hcap"><tbody>${rows.join("")}</tbody></table>` +
          (ok ? "" : `<div class="tnote">Not measurable: ${start ? start + (i + 1 >= CAP_DAYS && thin ? `; ${thin}` : "") : thin}</div>`) +
          `<div class="tnote">Typical: ${rfmt(K.R)} ${c.nm} per unit of search demand</div>` +
          `<div class="tnote">${span7(i)}. Days with data: Google Trends above zero and in Search Console.</div>`;
      } });
    };
    /* CTR chart (row 3, right): linear %, trailing 7-day; weeks under CTR_MIN impressions are gaps */
    const ctr = ci => {
      if (!hasG) return empty(ci, noG);
      const R = ctr7(gs), s = R.map(r => r && r.v != null ? r.v * 100 : null), inR = R.slice(r0, lastG + 1);
      if (!s.slice(r0, r1 + 1).some(v => v != null))
        return empty(ci, inR.some(Boolean) ? `Fewer than ${CTR_MIN} impressions in every week of these dates, too few for a stable CTR.`
          : "Not enough days with both impressions and clicks in these dates for a 7-day CTR.");
      if (inR.some(r => r && r.v == null)) notes[ci].textContent = `Gaps are weeks with under ${CTR_MIN} impressions, too few for a stable CTR.`;
      label(ci, CH[ci].t);
      const o = { color: "var(--gc)" };
      charts[ci] = plot(cells[ci], { r0, r1, lines: [{ s, color: o.color, ax: "l" }], fmtL: v => +v.toFixed(2) + "%", tip: i => {
        const r = R[i];
        if (!r) return head7(i) + (i > gscLast() ? notIn : `<div class="tnote">Fewer than 4 of the 7 days to here have both values.</div>`);
        return head7(i) + `<table class="tt"><tbody>
          <tr><td class="n">${sw(o)}CTR</td><td>${r.v == null ? "–" : (r.v * 100).toFixed(2) + "%"}</td></tr>
          <tr><td class="n">Clicks, ${r.n} days</td><td>${num(r.a)}</td></tr>
          <tr><td class="n">Impressions, ${r.n} days</td><td>${num(r.b)}</td></tr></tbody></table>` +
          (r.v == null ? `<div class="tnote">Under ${CTR_MIN} impressions, too few for a stable CTR</div>` : "") +
          `<div class="tnote">${wk7(i, r.n)} used</div>`;
      } });
    };

    const trendsThin = `Google Trends reports too few searches for these terms in ${a.name} to measure`;
    /* axis = the short title over that series' axis on a two-axis chart */
    const dem = hasD && { raw: D, color: "var(--f)", name: "Search demand", axis: "Search demand", ax: "l", kind: "d" };
    const imp = ax => hasG && { raw: gs.i, color: "var(--gi)", name: "Impressions", axis: "Impressions", ax, kind: "g" };
    const clk = hasG && { raw: gs.c, color: "var(--traffic)", fill: "var(--traffic-fill)", name: "Search traffic (clicks)", axis: "Clicks", ax: "r", kind: "g" };
    const timp = hasT && { raw: tAny.i, color: "var(--gi)", name: "Impressions on these searches", axis: "Impressions", ax: "r", kind: "g" };
    dual(0, [dem, imp("r")], true, G);
    capture(1, capI, { nm: "impressions", src: G, noun: "capture" });
    dual(2, [dem, clk], true, G);
    capture(3, capC, { nm: "clicks", src: G, noun: "capture" });
    dual(4, [imp("l"), clk], false, G);
    ctr(5);
    dual(6, [dem, timp], true, GT);
    /* the two charts stack below 860px (health.css), so the impressions chart is above, not to the left */
    capture(7, capT, { nm: "impressions on these searches", src: GT, noun: "share",
      gauge: `Our impressions on these searches (${matchMedia("(max-width: 860px)").matches ? "above" : "left"}) are the best gauge here` +
        (scope === "page" ? ": on page 1 they come close to the number of searches." : ".") });
    lastW = cells[0].clientWidth;
  }

  /* row 4's subtitle, and under its charts the tracked searches for the picked dates (Search Console's
     complete days only): each term, then any of the four (a search counted once); beside it the area's
     biggest matching searches over the export's fixed 90 days */
  function renderTracked(a, r0, r1) {
    const row = pane.querySelector(".htrack"), T = a.trk, ts = a.ts, top = ts && ts.top || [];
    const eg = top.slice(0, 2).map(q => `“${esc(q[0])}”`).join(", ");
    row.querySelector(".psub").innerHTML = `Search Console numbers for exactly the searches Google Trends counts: any search with all the words of one of the four terms, in any order${eg ? ` (e.g. ${eg})` : ""}, that showed ${esc(a.where)}.`;
    const box = row.querySelector(".htrk");
    const terms = T ? T.terms : a.kws;
    if (!terms) { box.innerHTML = `<div class="mempty">No Google Trends terms for ${esc(a.name)}, so no tracked searches.</div>`; return; }
    const g1 = Math.min(r1, gscLast()), hasDays = !!GSC && g1 >= r0, e1 = hasDays ? g1 : r1;
    const avg = s => { if (!s) return null; let v = 0, k = 0; for (let j = r0; j <= e1; j++) if (s[j] != null) { v += s[j]; k++; } return k ? v / k : null; };
    const tot = t => {
      if (!t || !hasDays) return null;
      let i = 0, c = 0, pw = 0, pi = 0, k = 0;
      for (let j = r0; j <= g1; j++) {
        if (t.i[j] == null) continue;
        k++; i += t.i[j]; c += t.c[j] || 0;
        if (t.p[j] != null && t.i[j]) { pw += t.p[j] * t.i[j]; pi += t.i[j]; }
      }
      return k ? { i, c, pos: pi ? pw / pi : null } : null;
    };
    const tr = (label, dem, t, cls) => `<tr${cls ? ` class="${cls}"` : ""}><td class="kw">${label}</td><td>${dem == null ? "–" : dem.toFixed(1)}</td>` +
      `<td>${t ? t.i.toLocaleString() : "–"}</td><td>${t ? t.c.toLocaleString() : "–"}</td>` +
      `<td>${t && t.i ? fpct(t.c / t.i) : "–"}</td><td>${t && t.pos != null ? fposn(t.pos) : "–"}</td></tr>`;
    const rows = terms.map((term, j) => {
      const di = a.kws ? a.kws.indexOf(term) : -1, ds = a.terms && a.terms[di >= 0 ? di : j];
      return tr(esc(term), avg(ds), tot(ts && ts.terms && ts.terms[j]));
    }).join("") + tr("Any of the four", avg(a.D), tot(ts && ts.any), "any");
    const cap = `${esc(a.st ? a.st.name : "National")}, ${dlab(r0)} – ${fdateY(DATA.dates[e1])}` +
      (hasDays ? (g1 < r1 ? " (Search Console's complete days in the picked dates)" : "") : ". Search Console has no complete days in these dates.");
    const tf = T ? fdate(T.topFrom) : "", tl = GSC ? fdate(GSC.lastComplete) : "";
    /* the biggest searches cover the export's fixed window (its last 90 complete days), not the picked dates */
    const topDays = T && GSC ? Math.round((Date.parse(GSC.lastComplete) - Date.parse(T.topFrom)) / 864e5) + 1 : 0;
    const topCap = `${esc(a.st ? a.st.name : "National")}, ${tf} – ${tl}: the last ${topDays} days of complete Search Console data. `
      + "This list uses a fixed window and doesn't follow the date picker.";
    const topBody = !ts ? `<div class="mempty">No Search Console data on these searches for ${esc(a.short)}.</div>`
      : top.length ? `<div class="httw"><table class="mtab htq"><colgroup><col class="qc"><col><col></colgroup>
          <thead><tr><th class="l">Search</th><th>Impressions</th><th>Clicks</th></tr></thead><tbody>` +
          top.slice(0, 6).map(q => `<tr><td class="kw">${esc(q[0])}</td><td>${kfmt(q[1])}</td><td>${kfmt(q[2])}</td></tr>`).join("") +
          `</tbody></table></div>`
      : `<div class="mempty">No matching searches in Search Console, ${tf} – ${tl}.</div>`;
    box.innerHTML = `<div class="htb"><h3>Tracked searches</h3><div class="htcap">${cap}</div>
      <div class="hhint">Swipe sideways for every column.</div>
      <div class="httw"><table class="mtab htt"><colgroup><col class="tc"><col><col><col><col><col></colgroup>
      <thead><tr><th class="l">Search term</th>
      <th title="Google Trends index on the area's own 0–100 scale, averaged over these dates (Any of the four: the mean of the four terms)">Search demand</th>
      <th title="${a.scope === "page" ? `Searches that showed ${esc(a.where)} (on page 1, nearly every search for the term)`
        : `Times ${esc(a.where)} showed on these searches. A search that showed two of them counts twice.`}">Impressions</th>
      <th title="Search Console clicks">Clicks</th>
      <th title="Share of those searches that clicked us">CTR</th>
      <th title="Impression-weighted average position (1 = top result)">Avg position</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>
      <div class="htb"><h3>Biggest matching searches</h3><div class="htcap">${ts ? topCap : "&nbsp;"}</div>${topBody}</div>`;
  }

  /* weeks (Monday–Sunday) overlapping the range, newest first; Search Console sides stop at GSC_LAST.
     Impressions vs demand = the week's Σ impressions ÷ Σ demand over its usable days (as capture7) ÷ the
     area's typical rate Ri; blank under CAP_DAYS usable days, a Trends signal under CAP_SIG or fewer than
     CAP_X.impressions impressions, or without Ri. */
  function renderTable(a, r0, r1, Ri) {
    const D = a.D, gs = a.gs, rows = [], minI = CAP_X.impressions;
    /* the capture rule over days lo..hi */
    const usable = (lo, hi) => {
      let n = 0, I = 0, d = 0, p = 0, g = 0, dn = 0;   /* g: days in Search Console; dn: of those, no Trends value */
      for (let j = lo; j <= hi; j++) {
        if (j > GSC_LAST || gs.i[j] == null) continue;
        g++; if (D[j] == null) dn++;
        if (D[j] > 0) { n++; I += gs.i[j]; d += D[j]; p += sigOf(a, j); }
      }
      return { n, I, d, p, g, dn, ok: n >= CAP_DAYS && p >= CAP_SIG && I >= minI };
    };
    for (let s = r0 - (dayAt(r0).getDay() + 6) % 7; s <= r1; s += 7) {
      const lo = Math.max(s, r0), hi = Math.min(s + 6, r1), gh = GSC_LAST == null ? -1 : Math.min(hi, GSC_LAST);
      let dS = 0, dN = 0, I = 0, C = 0, PW = 0, PI = 0, gN = 0;
      for (let j = lo; j <= hi; j++) {
        const d = D ? D[j] : null, gi = gs && j <= gh ? gs.i[j] : null;
        if (d != null) { dS += d; dN++; }
        if (gi == null) continue;
        gN++; I += gi; C += gs.c[j] || 0;
        if (gs.p[j] != null) { PW += gs.p[j] * gi; PI += gi; }
      }
      const days = hi - lo + 1, cut = [];
      if (days < 7) cut.push(`${days} of 7 days`);
      if (gs && gN < days) cut.push(gN ? `Search Console ${gN} of 7` : "no Search Console yet");
      const u = Ri ? usable(lo, hi) : null, ok = !!u && u.ok;
      let why = "";
      if (Ri && gN && !ok) {
        /* the data's first day or the picked dates clipped the week: say so rather than blame the signal,
           and add the signal's reason only when the clipped part had days enough to be measured */
        const start = s < 0 && lo === 0, clip = start ? `The data starts ${fdateY(DATA.dates[0])}: only ${days} of this week's days are in it`
          : days < 7 ? `The picked dates cut this week to ${days} of 7 days` : "";
        const thin = u.n < CAP_DAYS ? (u.g < CAP_DAYS ? `Search Console has only ${u.g} of this week's days; needs ${CAP_DAYS}+`
            : u.n ? `Google Trends was above zero on only ${u.n} of this week's ${u.g} days; needs ${CAP_DAYS}+`
            : `Google Trends reported ${u.dn ? "zero or nothing" : "zero"} on all ${u.g} days; needs ${CAP_DAYS}+ days above zero`)
          : u.p < CAP_SIG ? `Google Trends signal this week is ${u.p} (its four terms added up); needs ${CAP_SIG}+`
          : I > u.I ? `Only ${u.I.toLocaleString()} impressions on the ${u.n} days Google Trends was above zero; needs ${minI}+`
          : `${u.I.toLocaleString()} impressions this week; needs ${minI}+`;
        why = clip && (days < CAP_DAYS || !start && usable(Math.max(s, 0), Math.min(s + 6, N - 1)).ok) ? `${clip}, too few to measure`
          : clip ? `${clip}; ${thin.replace(/^Only /, "only ")}` : thin;
      }
      const cutTxt = cut.join(", ");
      rows.unshift(`<tr><td class="wk">${dlab(s)} – ${dlab(s + 6)}${cut.length ? `<span class="lbl">${cutTxt[0].toUpperCase() + cutTxt.slice(1)}</span>` : ""}</td>
        <td>${dN ? (dS / dN).toFixed(1) : "–"}</td><td>${gN ? I.toLocaleString() : "–"}</td>
        <td${why ? ` class="lbl" title="${why}"` : ""}>${ok ? cfmt(u.I / u.d / Ri) : "–"}</td>
        <td>${gN && I ? fpct(C / I) : "–"}</td><td>${gN ? C.toLocaleString() : "–"}</td><td>${PI ? fposn(PW / PI) : "–"}</td></tr>`);
    }
    pane.querySelector(".hwsub").textContent = `Weekly totals for ${a.name === "the US" ? "the whole US" : a.name}, Monday to Sunday, newest first: ${dlab(r0)} – ${dlab(r1)}`
      + (GSC ? `, with Search Console through ${fdate(GSC.lastComplete)}.` : ".");
    pane.querySelector(".htw").innerHTML = `<table class="mtab htab"><colgroup><col class="wkc"><col><col><col><col><col><col></colgroup>
      <thead><tr><th class="l">Week</th>
      <th title="Google Trends: mean of the area's four terms, averaged over the week's days with a value (0–100 index)">Search demand</th>
      <th title="Search Console impressions, summed">Impressions</th>
      <th title="The week's impressions per unit of search demand, compared with ${a.st ? esc(a.st.name) + "'s" : "the national"} typical (the median 7-day rate since ${fdate(DATA.dates[0])}). 1× = typical; 0.5× = half the usual impressions for that much searching. Blank when the week's signal is too thin.">Impressions vs demand</th>
      <th title="Clicks ÷ impressions">CTR</th>
      <th title="Search Console clicks (search traffic), summed">Traffic</th>
      <th title="Impression-weighted average position (1 = top result)">Avg position</th></tr></thead>
      <tbody>${rows.join("")}</tbody></table>`;
  }

  /* everything about method and sources, closed by default at the end of the tab */
  function renderNotes(a) {
    const tf = DATA.demand && DATA.demand.timeframe ? fdate(DATA.demand.timeframe.split(" ")[0]) : null;
    const nm = a.st ? esc(a.st.name) : "National", box = pane.querySelector(".hnotes");
    const open = !!box.querySelector("details.about[open]");   /* a re-render (area, dates, resize) keeps it open */
    box.innerHTML = `<details class="about"${open ? " open" : ""}><summary>About this data</summary><div class="about-body">
      <h4>Search demand</h4>
      <p>Google Trends daily interest, the mean of the area's four terms. It is a relative index on each area's own 0–100
      scale (100 = that area's busiest term-day${tf ? ` since ${tf}` : ""}), not a count of searches, so levels can't be compared
      across states or with the national line. A zero means searching stayed below Google's reporting threshold that day,
      not that nobody searched. The latest day is partial. Days when Google returned zeros for many areas at once are
      treated as missing.</p>
      <h4>Impressions, search traffic, CTR and position</h4>
      <p>Impressions, search traffic (clicks), CTR (clicks ÷ impressions) and avg position (impression-weighted, 1 = the top
      result) come from Google Search Console, web search, for ${esc(a.covers)}. Search Console runs about two days behind,
      so its lines and the 7-day rate charts stop at its last complete day${GSC ? ` (${fdateY(GSC.lastComplete)})` : ""}.</p>
      <h4>Impressions vs demand and traffic vs demand</h4>
      <p>Google Trends is relative, so impressions per unit of search demand mean little on their own. Each point adds up
      the 7 days to it, divides impressions (or clicks) by search demand and compares that with this area's typical: the
      median since ${fdate(DATA.dates[0])}. 1× = typical. Below 1× = shown less than demand predicts (a ranking or indexing
      gap); above 1× = more. The log scale makes halving and doubling look equally big.</p>
      <p>A gap means too thin a signal: a week counts only when Google Trends is above zero on at least ${CAP_DAYS} of its
      days, its four terms add up to at least ${CAP_SIG}, and it has at least ${CAP_X.impressions} impressions
      (${CAP_X.clicks} clicks for traffic). A typical needs ${CAP_MIN} such days.</p>
      <p>These terms miss fire-name searches, which bring much of our traffic; the tracked searches section measures
      exactly the searches they count. In the weekly table, impressions vs demand is the requested search demand ÷
      impressions, flipped.</p>
      <h4>CTR</h4>
      <p>Clicks ÷ impressions over the same trailing 7 days, left blank where those days had fewer than ${CTR_MIN}
      impressions. 7-day smoothing averages the two-line charts over a centered week; the 7-day rate charts and the
      tables are unaffected.</p>
      <h4>Tracked searches</h4>
      <p>Searches containing every word of one of the four terms, in any order, as Trends counts them. ${a.scope === "page"
        ? "On page 1 nearly every such search shows us, so impressions ≈ searches and CTR is our click share."
        : "Impressions are added up over the fire pages. A search that shows two of them counts twice, so impressions can run above the number of searches."}
      Absolute share isn't available (Search Console skips searches we didn't appear in; Google Trends has no absolute
      volume), so share is relative to typical. Search Console omits rare ones.</p>
      <h4>Terms for ${nm}</h4>
      <p>${a.geo[0].toUpperCase() + a.geo.slice(1)}: ${a.kws ? a.kws.map(k => `“${esc(k)}”`).join(", ") : "no Google Trends data for this area"}.</p>
      <h4>Coming later</h4>
      <p>Structures threatened, smoke impact and evacuations can be layered in once collected.</p>
    </div></details>`;
  }

  return {
    show() {
      if (!built) { build(); render(); }
      else if (cells[0].clientWidth !== lastW) render();
    },
    resize() { if (built && cells[0].clientWidth !== lastW) render(); },
    select(k) {
      if (!valid(k)) return;
      area = k;
      try { localStorage.setItem(skey, k); } catch (e) {}
      if (built) { sel.value = k; render(); }
    },
  };
}

tabHooks.hpage = makeHealthTab("hpage", "page");
tabHooks.hall = makeHealthTab("hall", "fire");
})();
