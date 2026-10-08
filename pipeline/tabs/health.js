/* ---------- Review Health tabs ----------
   One implementation, two scopes for Search Console: "page" = a state's own page (national: the
   homepage), "all" = every page of the state (national: the whole site). Search demand is the same in
   both: Google Trends, the mean of the area's four terms each day (meanSeries). */
(() => {
/* every chart keeps the right-axis margin, so all six share one x scale (and one set of date ticks) */
const HML = 40, HMR = 42, HMT = 10, HMB = 22;
/* demand averaging under 1 point (on Google's 0–100 scale) is at the reporting floor: one term moving
   a single point shifts it 25% or more, so a ratio over it is mostly rounding */
const FLOOR = 1;
const PRESETS = [
  { key: "30",  label: "Last 30 Days",  get: () => [N - 30, N - 1] },
  { key: "90",  label: "Last 90 Days",  get: () => [N - 90, N - 1] },
  { key: "180", label: "Last 180 Days", get: () => [N - 180, N - 1] },
  { key: "all", label: "All Data",      get: () => [0, N - 1] },
];
const ROWS = [
  { q: "Are we capturing search demand?",
    sub: "Impressions should rise and fall with searching. A falling ratio means Google shows us less for the same demand — a ranking or indexing gap." },
  { q: "Is demand turning into traffic?",
    sub: "Clicks from Google per unit of search demand: the whole funnel in one line." },
  { q: "Are impressions turning into traffic?",
    sub: "CTR falling while impressions hold points at titles, snippets or position." },
];
const CH = [
  { t: "Search demand and impressions" },
  { t: "Impressions ÷ demand", sub: "trailing 7-day · impressions per demand point" },
  { t: "Search demand and search traffic" },
  { t: "Traffic ÷ demand", sub: "trailing 7-day · clicks per demand point" },
  { t: "Impressions and search traffic" },
  { t: "CTR", sub: "clicks ÷ impressions, trailing 7-day · %" },
];
const tickFmt = v => v >= 1e6 ? +(v / 1e6).toFixed(2) + "M" : v >= 1000 ? +(v / 1000).toFixed(2) + "k" : String(+v.toFixed(2));
const num = v => v == null ? "–" : v < 10 && v % 1 ? v.toFixed(1) : Math.round(v).toLocaleString();
const rfmt = v => v == null ? "–" : v >= 100 ? Math.round(v).toLocaleString() : v >= 1 ? v.toFixed(1) : v.toFixed(2);
const dfmt = v => v == null ? "–" : v.toFixed(1);
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
const boxH = w => w < 480 ? 180 : 220;
const floorNote = m => `Demand averaged ${m.toFixed(2)} points on these days — at Google Trends' reporting floor, so this ratio is mostly rounding.`;

/* trailing 7-day ratio Σnum ÷ Σden over days d-6..d where both exist; for demand ratios only days
   Google reported searches (a zero there means "below its threshold"). Null under 4 such days and
   after Search Console's last complete day (the window would only be shedding older days).
   m = mean denominator over the days used. */
function ratio7(nm, dn, needDen) {
  const last = GSC_LAST == null ? N - 1 : GSC_LAST;
  return DATA.dates.map((_, d) => {
    if (d > last) return null;
    let a = 0, b = 0, n = 0;
    for (let j = Math.max(0, d - 6); j <= d; j++) {
      if (nm[j] == null || dn[j] == null || (needDen && !dn[j])) continue;
      a += nm[j]; b += dn[j]; n++;
    }
    return n >= 4 && b > 0 ? { v: a / b, a, b, n, m: b / n } : null;
  });
}

function areaData(scope, key) {
  const st = key === "national" ? null : DATA.states.find(s => s.key === key) || null;
  const dm = DATA.demand ? (st ? DATA.demand.states[st.key] : DATA.demand.national) : null;
  const gs = !GSC ? null : scope === "page" ? (st ? st.gscPage : GSC.home) : (st ? st.gsc && st.gsc.web : GSC.site);
  return {
    st, name: st ? st.name : "the US", hasDm: !!dm, kws: dm ? dm.kws : null, terms: dm ? dm.s : null,
    D: dm ? meanSeries(dm.s) : null, gs: gs || null,
    geo: st ? `searches made in ${st.name} (geo US-${st.abbr})` : "searches across the US (geo US)",
    covers: scope === "page" ? (st ? `fires.cornea.is/state/${st.key} only` : "the fires.cornea.is homepage only")
      : (st ? `every ${st.name} page — /state/${st.key} and its fire pages` : "every page on fires.cornea.is"),
    short: scope === "page" ? (st ? `the ${st.name} state page` : "the homepage") : (st ? `${st.name}'s pages` : "the site"),
  };
}

/* one SVG chart into `box`: lines on a left axis (which owns the gridlines) and optionally a right
   axis that reuses those gridlines with its own nice step. A line's `weak` flags (per day) draw those
   stretches dashed and faint. Returns what the hover layer needs. */
function plot(box, o) {
  const { r0, r1, lines } = o;
  const w = Math.max(260, Math.round(box.clientWidth)), h = boxH(w);
  const hasR = lines.some(l => l.ax === "r");
  const mr = HMR, iw = w - HML - mr, ih = h - HMT - HMB;
  const X = i => HML + (i - r0) / (r1 - r0) * iw;
  const top = ax => { let m = 0; lines.forEach(l => { if (l.ax === ax) for (let i = r0; i <= r1; i++) if (l.s[i] > m) m = l.s[i]; }); return m; };
  const tl = top("l"), tr = top("r");
  const L = niceAxis(tl), nGrid = Math.round(L.ymax / L.step);
  const rStep = hasR ? niceUp(tr / nGrid, 1) : 1;
  const Yl = v => HMT + ih - v / L.ymax * ih, Yr = v => HMT + ih - v / (rStep * nGrid) * ih;
  const Yof = l => l.ax === "r" ? Yr : Yl;
  const colOf = ax => (lines.find(l => l.ax === ax) || {}).color;
  const fmtL = o.fmtL || tickFmt;
  const mono = `font-family="IBM Plex Mono, monospace" font-size="9.5"`;
  let g = "";
  for (let k = 0; k <= nGrid; k++) {
    const y = Yl(k * L.step);
    g += `<line x1="${HML}" x2="${w - mr}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(${k ? "--grid" : "--axis"})" stroke-width="1"/>`;
    /* a series that never leaves zero gets only its 0 label: the rest of the scale would be invented */
    if (!k || tl > 0) g += `<text x="${HML - 6}" y="${(y + 3.3).toFixed(1)}" text-anchor="end" fill="${colOf("l")}" ${mono}>${fmtL(k * L.step)}</text>`;
    if (hasR && (!k || tr > 0)) g += `<text x="${w - mr + 6}" y="${(y + 3.3).toFixed(1)}" fill="${colOf("r")}" ${mono}>${tickFmt(k * rStep)}</text>`;
  }
  let lastR = -1e9;
  xTicks(r0, r1, iw).forEach(([i, t, anchor]) => {
    const tw = t.length * 5.8;
    let x = X(i);
    if (anchor === "middle") x = Math.min(w - mr - tw / 2 + 4, Math.max(HML + tw / 2 - 4, x));
    const left = anchor === "start" ? x : x - tw / 2;
    if (left < lastR + 6) return;      /* never let two labels touch */
    lastR = left + tw;
    g += `<text x="${x.toFixed(1)}" y="${h - 5}" text-anchor="${anchor}" fill="var(--muted)" ${mono}>${t}</text>`;
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
  const stroke = (l, s, extra) => {
    const Y = Yof(l), pt = i => X(i).toFixed(1) + " " + Y(s[i]).toFixed(1), rs = runs(s);
    /* a day with no neighbours has no segment: draw it as a dot */
    rs.filter(r => r.length === 1).forEach(([i]) => { g += `<circle cx="${X(i).toFixed(1)}" cy="${Y(s[i]).toFixed(1)}" r="1.8" fill="${l.color}"${extra}/>`; });
    const d = rs.filter(r => r.length > 1).map(r => "M" + r.map(pt).join("L")).join("");
    if (d) g += `<path d="${d}" fill="none" stroke="${l.color}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"${extra}/>`;
  };
  lines.forEach(l => {
    if (!l.weak) return stroke(l, l.s, "");
    stroke(l, l.s, ` opacity="0.6" stroke-dasharray="3 3"`);   /* the whole line, faint; firm days drawn over it */
    stroke(l, l.s.map((v, i) => l.weak[i] ? null : v), "");
  });
  g += `<line class="xh" x1="-10" x2="-10" y1="${HMT}" y2="${HMT + ih}" stroke="var(--muted)" stroke-width="1" opacity="0"/><g class="hd"></g>`;
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
      xh.setAttribute("x1", x); xh.setAttribute("x2", x); xh.setAttribute("opacity", "0.6");
      hd.innerHTML = lines.map(l => l.s[i] == null ? "" :
        `<circle cx="${x}" cy="${Yof(l)(l.s[i]).toFixed(1)}" r="4" fill="${l.color}" stroke="var(--surface)" stroke-width="2"/>`).join("");
    },
  };
}

function makeHealthTab(key, scope) {
  const pane = document.getElementById("pane-" + key), skey = `wdo-${key}-state`;
  const natLabel = scope === "page" ? "National · Homepage" : "National · Whole Site";
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
    if (i == null || !charts[ci]) { tip.style.display = "none"; hov = null; return; }
    const r = cells[ci].getBoundingClientRect();
    hov = { ci, dx: cx - r.left, dy: cy - r.top };
    tip.innerHTML = charts[ci].tip(i);
    tip.style.display = "block";
    place(cx, cy);
  }

  function build() {
    built = true;
    pane.innerHTML = `<div class="tbar">
        <select class="statef" aria-label="Area"><option value="national">${natLabel}</option>` +
        DATA.states.map(s => `<option value="${s.key}">${esc(s.name)}</option>`).join("") + `</select>
        <label class="smooth"><input type="checkbox"> 7-Day Smooth</label>
        <span class="tlabel hscope"></span></div>` +
      ROWS.map((r, ri) => `<section class="panel hrow"><h2>${r.q}</h2><div class="psub">${r.sub}</div><div class="hgrid">` +
        [0, 1].map(k => { const c = CH[ri * 2 + k]; return `<div class="hc"><div class="hch"><h3>${c.t}</h3>
          <div class="${c.sub ? "hsub" : "hlg"}">${c.sub || ""}</div></div>
          <div class="hbox" role="group" aria-roledescription="chart"></div><div class="hnote"></div></div>`; }).join("") +
        `</div></section>`).join("") +
      `<section class="panel"><h2>The data</h2><div class="psub"><span class="hwsub"></span><span class="hhint"> · Swipe sideways for every column</span></div><div class="htw"></div></section>
      <div class="tabnotes hnotes"></div><div class="hsr" aria-live="polite"></div>`;
    const bar = pane.querySelector(".tbar");
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
    const hasD = any(D), hasG = !!gs && any(gs.i);
    let zero = 0, miss = 0;
    for (let i = r0; i <= r1; i++) { if (!D || D[i] == null) miss++; else if (!D[i]) zero++; }
    const sparse = hasD && zero + miss > n / 2;
    const gThru = GSC ? ` (through ${fdate(GSC.lastComplete)})` : "";
    pane.querySelector(".hscope").textContent = `Search Console${gThru}: ${a.covers} · Google Trends: ${a.geo}`;
    const wr = renderTable(a, r0, r1);
    renderNotes(a);

    const noD = a.hasDm ? `Google Trends has no values for ${a.name} in these dates.` : `No Google Trends data for ${a.name}.`;
    let gEnd = -1;
    if (gs) for (let i = N - 1; i >= 0; i--) if (gs.i[i] != null) { gEnd = i; break; }
    const noG = !GSC ? "No Search Console data in this build."
      : gEnd < 0 ? `No Search Console data for ${a.short}.`
      : gEnd < r0 ? `Search Console data for ${a.short} runs through ${fdate(DATA.dates[gEnd])}, before these dates.`
      : `No Search Console data for ${a.short} in these dates.`;
    const zTxt = `${zero + miss} of ${n} days are zero${miss ? " or missing" : ""}`;
    const empty = (ci, msg) => {
      cells[ci].innerHTML = `<div class="hempty" style="--hh:${boxH(Math.max(260, cells[ci].clientWidth))}px">${msg}</div>`;
      cells[ci].setAttribute("aria-label", msg);
      cells[ci].tabIndex = -1;
      charts[ci] = null;
    };
    const legend = (ci, lines) => {
      cells[ci].parentNode.querySelector(".hlg").innerHTML = lines.map(l =>
        `<span>${keyOf(l)}${l.name}${lines.length > 1 ? ` · ${l.ax === "l" ? "left" : "right"}` : ""}</span>`).join("");
    };
    const notes = [...pane.querySelectorAll(".hnote")];
    notes.forEach(el => el.textContent = "");
    const label = (ci, t) => {
      cells[ci].setAttribute("aria-label", `${t} for ${a.name}, ${dlab(r0)} – ${dlab(r1)}. Arrow keys step through the days.`);
      cells[ci].tabIndex = 0;
    };
    const sparseNote = `Google Trends reports zero for these terms in ${a.name} on ${zero} of ${n} days${miss ? ` (and has no value on ${miss} more)` : ""} — `
      + `searching stayed below its reporting threshold, so a flat line means too few searches to report.`;

    /* left-hand chart: two series, each on its own axis (smoothed when 7-Day Smooth is on) */
    const dual = (ci, defs, withD) => {
      const lines = defs.filter(Boolean).map(d => ({ ...d, s: sm(d.raw) }));
      if (lines.length === 1) lines[0].ax = "l";
      legend(ci, lines);
      const why = [withD && !hasD ? noD : "", hasG ? "" : noG].filter(Boolean).join(" ");
      if (!lines.length) return empty(ci, why);
      notes[ci].textContent = [why, withD && sparse ? sparseNote : ""].filter(Boolean).join(" ");
      label(ci, CH[ci].t);
      charts[ci] = plot(cells[ci], { r0, r1, lines, fmtL: tickFmt, tip: i => {
        const hasDem = lines.some(l => l.kind === "d"), hasGsc = lines.some(l => l.kind === "g");
        const f = (l, v) => l.kind === "d" ? dfmt(v) : num(v);
        const rows = lines.map(l => `<tr><td class="n">${sw(l)}${l.name}</td><td>${f(l, l.s[i])}</td>` +
          (smoothOn ? `<td class="zero">${f(l, l.raw[i])}</td>` : "") + `</tr>`).join("");
        const tn = [];
        if (hasGsc && gs.i[i] == null) tn.push(GSC_LAST != null && i > GSC_LAST ? "Search Console: not in yet (~2-day lag)" : "Search Console: no data this day");
        if (hasDem && a.terms) tn.push(D[i] == null ? "Google Trends: no value this day"
          : "Google Trends, this day: " + a.kws.map((k, j) => `${esc(k)} ${a.terms[j][i] == null ? "–" : a.terms[j][i]}`).join(" · ") + (i === N - 1 ? " (partial day)" : ""));
        return `<div class="d">${fdateY(DATA.dates[i])}</div><table class="tt">` +
          (smoothOn ? `<thead><tr><th></th><th>7-day avg</th><th>day</th></tr></thead>` : "") + `<tbody>${rows}</tbody></table>` +
          tn.map(t => `<div class="tnote">${t}</div>`).join("");
      } });
    };
    /* trailing 7-day ratio chart; demand ratios dash the stretches where demand sits at the floor */
    const ratio = (ci, o) => {
      if (o.block) return empty(ci, o.block);
      const R = ratio7(o.nm, o.dn, o.needDen), s = R.map(r => r && r.v * (o.pct ? 100 : 1));
      if (!s.slice(r0, r1 + 1).some(v => v != null))
        return empty(ci, `Not enough days with both ${o.dnName} and ${o.nmName} in these dates for a 7-day ratio.`);
      const weak = o.needDen ? R.map(r => !!r && r.m < FLOOR) : null;
      if (weak && weak.slice(r0, r1 + 1).some(Boolean))
        notes[ci].textContent = `Dashed where demand averaged under ${FLOOR} point: at Google Trends' reporting floor a 1-point step in one term moves demand 25% or more, so the ratio there is mostly rounding.`;
      label(ci, CH[ci].t);
      charts[ci] = plot(cells[ci], { r0, r1, lines: [{ s, weak, color: o.color, ax: "l" }], fmtL: o.pct ? v => +v.toFixed(2) + "%" : tickFmt, tip: i => {
        const r = R[i], head = `<div class="d">${fdateY(DATA.dates[i])}<span class="lbl">7 days to here</span></div>`;
        if (!r) return head + `<div class="tnote">${GSC_LAST != null && i > GSC_LAST ? "Search Console: not in yet (~2-day lag)"
          : `Fewer than 4 of the 7 days to here have both values${o.needDen ? " (and searches Google reported)" : ""}.`}</div>`;
        return head + `<table class="tt"><tbody>
          <tr><td class="n">${sw(o)}${CH[ci].t}</td><td>${o.pct ? (r.v * 100).toFixed(2) + "%" : rfmt(r.v) + ` <span class="u">${o.unit}</span>`}</td></tr>
          <tr><td class="n">${o.nmName}, ${r.n} days</td><td>${o.nmFmt(r.a)}</td></tr>
          <tr><td class="n">${o.dnName}, ${r.n} days</td><td>${o.dnFmt(r.b)}</td></tr></tbody></table>
          <div class="tnote">${dlab(Math.max(0, i - 6))} – ${dlab(i)} · ${r.n} of 7 days used${o.needDen && r.n < 7 ? " (days with a Google Trends value above zero and Search Console data)" : ""}</div>` +
          (weak && weak[i] ? `<div class="tnote">${floorNote(r.m)}</div>` : "");
      } });
    };

    const dem = hasD && { raw: D, color: "var(--f)", name: "Search demand", ax: "l", kind: "d" };
    const imp = ax => hasG && { raw: gs.i, color: "var(--gi)", name: "Impressions", ax, kind: "g" };
    const clk = hasG && { raw: gs.c, color: "var(--traffic)", fill: "var(--traffic-fill)", name: "Search traffic (clicks)", ax: "r", kind: "g" };
    const sparseMsg = `Google Trends reports too few searches for these terms in ${a.name} to compute a ratio — ${zTxt}.`;
    const dBlock = !hasD ? noD : !hasG ? noG : sparse ? sparseMsg : null;
    dual(0, [dem, imp("r")], true);
    ratio(1, { block: dBlock && dBlock + (sparse && hasG && wr ? ` The table below has it for the ${wr} week${wr > 1 ? "s" : ""} where Google reported searches on most days.` : ""),
      nm: hasG && gs.i, dn: D, needDen: true, color: "var(--ink-2)", unit: "impressions per demand point",
      nmName: "impressions", dnName: "demand points", nmFmt: num, dnFmt: dfmt });
    dual(2, [dem, clk], true);
    ratio(3, { block: dBlock, nm: hasG && gs.c, dn: D, needDen: true, color: "var(--ink-2)", unit: "clicks per demand point",
      nmName: "clicks", dnName: "demand points", nmFmt: num, dnFmt: dfmt });
    dual(4, [imp("l"), clk], false);
    ratio(5, { block: hasG ? null : noG, nm: hasG && gs.c, dn: hasG && gs.i, pct: true, color: "var(--gc)",
      nmName: "clicks", dnName: "impressions", nmFmt: num, dnFmt: num });
    lastW = cells[0].clientWidth;
  }

  /* weeks (Monday–Sunday) overlapping the range, newest first; Search Console sides stop at GSC_LAST.
     Returns how many weeks have an Impressions ÷ Demand value. */
  function renderTable(a, r0, r1) {
    const D = a.D, gs = a.gs, rows = [];
    let withRatio = 0;
    for (let s = r0 - (dayAt(r0).getDay() + 6) % 7; s <= r1; s += 7) {
      const lo = Math.max(s, r0), hi = Math.min(s + 6, r1), gh = GSC_LAST == null ? -1 : Math.min(hi, GSC_LAST);
      let dS = 0, dN = 0, I = 0, C = 0, PW = 0, PI = 0, gN = 0, rI = 0, rD = 0, both = 0, rep = 0;
      for (let j = lo; j <= hi; j++) {
        const d = D ? D[j] : null, gi = gs && j <= gh ? gs.i[j] : null;
        if (d != null) { dS += d; dN++; }
        if (gi == null) continue;
        gN++; I += gi; C += gs.c[j] || 0;
        if (gs.p[j] != null) { PW += gs.p[j] * gi; PI += gi; }
        if (d != null) { both++; if (d > 0) { rep++; rI += gi; rD += d; } }
      }
      const days = hi - lo + 1, cut = [];
      if (days < 7) cut.push(`${days} of 7 days`);
      if (gs && gN < days) cut.push(gN ? `Search Console ${gN} of 7` : "no Search Console yet");
      const ok = rep * 2 > both && rD > 0, weak = ok && rD / rep < FLOOR;
      if (ok) withRatio++;
      const rAttr = !ok ? (both ? ` class="lbl" title="Google Trends reported searches on ${rep} of ${both} days this week — too few for a ratio"` : "")
        : weak ? ` class="lbl" title="${floorNote(rD / rep)}"` : "";
      rows.unshift(`<tr><td class="wk">${dlab(s)} – ${dlab(s + 6)}${cut.length ? ` <span class="lbl">· ${cut.join(" · ")}</span>` : ""}</td>
        <td>${dN ? (dS / dN).toFixed(1) : "–"}</td><td>${gN ? I.toLocaleString() : "–"}</td>
        <td${rAttr}>${ok ? rfmt(rI / rD) : "–"}</td>
        <td>${gN && I ? fpct(C / I) : "–"}</td><td>${gN ? C.toLocaleString() : "–"}</td><td>${PI ? fposn(PW / PI) : "–"}</td></tr>`);
    }
    pane.querySelector(".hwsub").textContent = `Weekly, Monday–Sunday, newest first · ${a.name === "the US" ? "National" : a.name} · ${dlab(r0)} – ${dlab(r1)}`
      + (GSC ? ` · Search Console through ${fdate(GSC.lastComplete)}` : "");
    pane.querySelector(".htw").innerHTML = `<table class="mtab htab"><colgroup><col class="wkc"><col><col><col><col><col><col></colgroup>
      <thead><tr><th class="l">Week</th>
      <th title="Google Trends: mean of the area's four terms, averaged over the week's days with a value (0–100 index)">Search Demand</th>
      <th title="Search Console impressions, summed">Impressions</th>
      <th title="Impressions ÷ search demand — the same way round as the 'Impressions ÷ demand' chart (the requested SD/Impressions column, flipped so higher = more of the demand captured). Σ impressions ÷ Σ demand over the week's days Google reported searches; blank when it reported zero on half the days or more; grey when demand on those days averaged under ${FLOOR} point (Google Trends' reporting floor, so mostly rounding).">Impressions ÷ Demand</th>
      <th title="Clicks ÷ impressions">CTR</th>
      <th title="Search Console clicks (search traffic), summed">Traffic</th>
      <th title="Impression-weighted average position (1 = top result)">Avg Position</th></tr></thead>
      <tbody>${rows.join("")}</tbody></table>`;
    return withRatio;
  }

  function renderNotes(a) {
    const tf = DATA.demand && DATA.demand.timeframe ? fdate(DATA.demand.timeframe.split(" ")[0]) : null;
    pane.querySelector(".hnotes").innerHTML = `
      <p><b>Search demand</b> = Google Trends daily interest, the mean of the area's four terms. It is a relative index on
      each area's own 0–100 scale (100 = that area's busiest term-day${tf ? ` since ${tf}` : ""}), not a count of searches, so levels
      can't be compared across states or with the national line. A zero means searching stayed below Google's reporting
      threshold that day, not that nobody searched. The latest day is partial; days when Google returned zeros for many
      areas at once are treated as missing.</p>
      <p><b>Impressions</b>, <b>search traffic</b> (clicks), <b>CTR</b> (clicks ÷ impressions) and <b>avg position</b>
      (impression-weighted, 1 = the top result) come from Google Search Console, web search, for ${esc(a.covers)}. Search
      Console runs about two days behind, so its lines and the ratios stop at its last complete day${GSC ? ` (${fdateY(GSC.lastComplete)})` : ""}.</p>
      <p><b>Ratios</b> (right-hand charts) are trailing 7-day: for each day, the top summed over the 7 days ending that day ÷
      the bottom summed over the same days, using days where both exist — for the two demand ratios, only days Google
      reported searches (above zero) — and left blank when fewer than 4 days qualify. The demand ratios are hidden when
      Google reports zero on more than half the picked days, and dashed where demand averaged under ${FLOOR} point (its
      reporting floor, where 1-point rounding swamps the ratio). The table's Impressions ÷ Demand uses the same rules per
      week (grey = at the floor). 7-Day Smooth averages the left-hand charts over a centered week; ratios and the table are unaffected.</p>
      <p><b>Terms for ${a.st ? esc(a.st.name) : "National"}</b>, ${a.geo}: ${a.kws ? a.kws.map(k => `“${esc(k)}”`).join(", ") : "no Google Trends data for this area"}.</p>
      <p>Structures threatened, smoke impact and evacuations can be layered in once collected.</p>`;
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
tabHooks.hall = makeHealthTab("hall", "all");
})();
