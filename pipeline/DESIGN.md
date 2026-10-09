# WFE SEO Dashboard: design system (warm light redesign)

Source of truth: the `:root` block at the top of the `<style>` in `pipeline/build_dashboard.py`
This file explains it. Follow it when changing any tab.

The look in one line: a warm sand page, paper-white cards for real sections only, warm charcoal-brown ink,
one deep-juniper accent for everything you can click, soft status pills, calm chart colors, Figtree everywhere
except the page title and section titles (Bricolage Grotesque). Single light theme. No dark mode, no monospace.

---

## 1. Hard rules

1. **Only tokens.** Every color in CSS and in JS-generated HTML/SVG is `var(--token)`. No hex, rgb, `#fff`, named colors.
   (Exception: the tokens themselves, and the favicon data URI.)
2. **No dark mode.** No `prefers-color-scheme` or `[data-theme]` blocks anywhere, including tabs/*.css.
3. **No monospace, no uppercase labels.** No `IBM Plex …`, `ui-monospace`, `monospace`, `text-transform: uppercase`,
   letter-spaced caps. Delete `font-family` declarations in tab CSS (body already sets `var(--font-ui)`); if you must set one,
   use `var(--font-ui)`. In SVG, the global rule `svg text { font-family: var(--font-ui) }` overrides any
   `font-family="…"` attribute, but remove stale `IBM Plex` attributes when you touch a line.
4. **Tabular digits wherever numbers line up**: tables, axis ticks, tooltips, stats rows (`font-variant-numeric: tabular-nums`;
   tables and `svg text` already get it). Big standalone numbers may stay proportional.
5. **Keep every number, feature and note.** De-clutter by relocating long text into `details.about`, not by deleting it.
6. **Phone width (390px):** no horizontal page scroll. Wide tables scroll inside their own `overflow-x: auto` box.
   Check: `document.documentElement.scrollWidth === clientWidth` on every tab at `--mobile`.

---

## 2. Color tokens

### Ground and ink
| Token | Value | Use |
|---|---|---|
| `--bg` | `#f3ede3` | Page ground (warm sand). Sticky controls bar background. |
| `--surface` | `#fffcf7` | Cards/panels, popovers, chart plot area, buttons and selects. Halo/ring color around chart marks. |
| `--surface-2` | `#f8f3eb` | Quiet inset fill: empty states, summary/total rows, hover on paper controls. |
| `--ink` | `#2b2620` | Primary text, values (14.6:1 on surface). |
| `--ink-2` | `#5c5248` | Secondary text, table headers, notes, the one-line section description (7.4:1). |
| `--muted` | `#766a5e` | Captions, axis labels, hints, disabled-ish labels (5.1:1 on surface, 4.5:1 on bg). Lowest text color allowed. |
| `--border` | `#e4dacb` | Card edges, header rule under table heads, dividers between blocks. |
| `--line` | `#eee6da` | Table row hairlines, tooltip header rule. |
| `--control-border` | `#d5c8b5` | Edges of buttons, chips, selects, inputs, calendar nav. |
| `--grid` | `#ece4d8` | Chart gridlines (1px, solid). |
| `--axis` | `#cfc2af` | Chart baseline / zero line, "1x" reference lines, dashed low-signal outlines, group-header rules. |
| `--chip-bg` | `rgba(110,86,56,.07)` | Translucent warm tint: row hover, highlighted row, tab hover. Works on bg and surface. Not a button fill. |
| `--tooltip-bg` | `#fffcf7` | Hover readout and popover background. |
| `--shadow-card` | `0 1px 2px rgba(74,56,36,.05)` | Cards only. |
| `--shadow-pop` | two-layer warm shadow | Popovers, tooltip. |

### Interactive accent (deep juniper) — the only accent
| Token | Value | Use |
|---|---|---|
| `--accent` | `#2f6153` | Selected tab text + underline, focus rings, selected calendar day, links, active segmented button (6.9:1). |
| `--accent-strong` | `#244c41` | Hover/pressed accent; text on `--accent-soft`. |
| `--accent-soft` | `#e1ece5` | Quiet selected fill: active date preset, in-range days, open popover button, disclosure hover. |
| `--accent-ink` | `#fffcf7` | Text on a solid `--accent` fill. |
| `--fm` | `var(--accent)` | Legacy alias, still used for focus rings in tabs/*.css. Prefer `--accent` in new code. |
| `--range-bg` | `var(--accent-soft)` | Legacy alias for date-range days. |

Never use the accent for data, status, or decoration. Never use a chart or status color for UI chrome.

### Semantic state (separate from the accent, always with a label or shape)
| Token | Value | Use |
|---|---|---|
| `--good` | `#4a7a2c` | Leaf green: up arrows/deltas as text, "outperforming" marks (5.0:1). |
| `--good-soft` | `#e5edd8` | Background of good pills/chips. |
| `--good-ink` | `#3d6a22` | Text on `--good-soft` (5.3:1). |
| `--bad` | `#a3412c` | Brick red: down arrows/deltas, "missing demand" marks, `td.bad` (6.1:1). |
| `--bad-soft` | `#f7e2da` | Background of bad pills. |
| `--bad-ink` | `#8c3423` | Text on `--bad-soft`; red labels in charts (6.4:1). |
| `--neutral` | `#8a7e71` | Warm grey marks for "tracking" / "low signal" (hollow rings). |
| `--neutral-soft` | `#eee7dc` | Background of neutral pills. |
| `--neutral-ink` | `#5c5248` | Text on `--neutral-soft` (6.2:1). |

Good vs bad collapse for red-green colorblind readers (deutan ΔE 1.5), like every red/green pair. So status is
**never color alone**: pills carry a label and a dot; arrows carry ↑/↓; chart marks carry a shape (see §7).

### Chart series (meaning unchanged, names unchanged)
| Token | Value | Series | Mark |
|---|---|---|---|
| `--traffic` | `#34762e` | Our traffic / search traffic (clicks) | 2px line + `--traffic-fill` area wash |
| `--traffic-fill` | `rgba(52,118,46,.12)` | Area under traffic | fill only |
| `--gi` | `#3069b2` | Search Console impressions | 2px line |
| `--gc` | `#a34a7c` | Search Console CTR | 1.75px line |
| `--gp` | `#54493e` | Search Console avg position (dotted) and best position (dashed) | 2px dotted `0.1 3.6` round caps / 1.5px dashed `5 3` |
| `--f` | `#049e98` | Google Trends "fire {state}" = search demand (also health tabs' "Search demand") | 1.75-2px line; abbreviation variant dashed `6 4` |
| `--wf` | `#a68f37` | Google Trends "wildfire {state}" | 1.75px line |
| `--fn` | `#957fd6` | Google Trends "fire near me" / "fire near {city}" (dashed) | 1.75px line |
| `--fire-mk` | `#de7431` | Fire starts (ember) | diamonds on the baseline with a thin `--ink-2` edge; hollow = not impactful |

Copy that names colors should say: traffic **green**, impressions **blue**, CTR **berry/pink**, position **dark grey**
(dotted = average, dashed = best), search demand **teal**, "wildfire {state}" **mustard**, "fire near me" **lavender**,
fire starts **orange diamonds**. (The old footer's "yellow diamonds" is wrong; fix it when you move that text.)

**Validation** (dataviz skill validator, light mode, surface `#fffcf7`):
- Core four lines that share charts on every tab (traffic, gi, gc, f), all pairs: PASS. Worst CVD ΔE 8.6, normal 15.8, all ≥ 3:1.
- All six colored lines (traffic, gi, gc, f, wf, fn), all pairs: PASS. Worst CVD ΔE 8.6, normal 15.7.
- Known, accepted exceptions (each has a non-color channel):
  - `--gp` is a deliberate neutral (C 0.023, L 0.41): it is always dotted or dashed, on its own right-hand axis, so
    its identity is the dash pattern.
  - `--fire-mk` vs `--wf`: CVD ΔE 2.6. Fire starts are diamond markers, never lines; wf is hidden by default.
  - `--fire-mk` vs `--traffic`: CVD ΔE 7.9 (floor band); again diamonds vs line + area.
- Do not add new series colors. A new series reuses the token of the measure it shows. If a chart needs more than
  these, use dash patterns or small multiples, not a new hue.

---

## 3. Type

Faces (Google Fonts link already in the head):
- `--font-display`: **Bricolage Grotesque** (opsz 12-96, weights 500-700). Only for `h1` and section `h2`.
  Never for numbers, tables, buttons, chart text, or card-level titles.
- `--font-ui`: **Figtree** (400-700, italic 400-600). Everything else, including numbers (it has true tabular figures).

| Token | Size | Use |
|---|---|---|
| `--fs-h1` | 26px (23px under 600px) | Page title, display 700, -0.015em. |
| `--fs-h2` | 19px (18px under 600px) | Section heading inside a card: display 650, -0.01em, line-height 1.25. |
| `--fs-h3` | 15px | Sub-heading inside a section (chart title, table title): UI 600, ink. |
| `--fs-body` | 15px | Body text, line-height 1.5. |
| `--fs-table` | 14px | Table cells, buttons, selects, chips, notes, `.psub`, disclosure body. |
| `--fs-small` | 13px | Table headers, captions, axis notes, `.tlabel`, tooltip text, secondary stats. |
| `--fs-pill` | 12.5px | Pills (12px inside tables/tooltips). |
| `--fs-axis` | 11.5px | Chart tick labels. Axis titles 11px weight 600. Nothing in a chart below 10px. |

Weights: 400 body, 500 controls, 600 labels/values/headers, 650 h2, 700 h1. Sentence case everywhere
("Missing demand", "Search traffic", "Avg position"); `.mtab th::first-letter` and tooltip `th::first-letter` are
uppercased by CSS as a safety net, but author strings in sentence case. Headings get `text-wrap: balance` (global).

---

## 4. Spacing, shape, width

Spacing scale (use these, nothing in between): `--sp-1` 4 · `--sp-2` 8 · `--sp-3` 12 · `--sp-4` 16 · `--sp-5` 24 · `--sp-6` 32 · `--sp-7` 48 (px).
- Card padding `--sp-5` (16px under 600px). Gap between cards/sections `--sp-5`.
- Heading → description `--sp-1`; description → content `--sp-4`; between sub-blocks inside a card `--sp-5`.
- Lay out siblings with flex/grid `gap`, not margins.

Radii: `--r-sm` 6 · `--r-md` 10 (inner boxes, tooltip, table wrappers) · `--r-lg` 14 (cards) · `--r-pill` 999 (buttons, chips, selects, pills).
Reading width: `--read` = 72ch for any paragraph of explanation.
Page: `.wrap` max 1440px, side gutter `clamp(16px, 3vw, 32px)`.

---

## 5. Components (all defined in build_dashboard.py; use the classes, don't restyle them per tab)

**Page header + tabs.** `header.page > h1 + p.lede`, then `nav.tabs` (underline tabs, 15px/600, selected = accent
text + 3px accent underline, hover = `--chip-bg`). Owned by build_dashboard.py.

**Section card** — the only boxed thing on a page. Use for real sections, not for every sub-block.
```html
<section class="panel">
  <h2>Are we capturing search demand?</h2>
  <div class="psub">One plain sentence saying what this section answers.</div>
  …content (sub-blocks separated by space, not by more boxes)…
  <details class="about"><summary>How this is calculated</summary>
    <div class="about-body"><p>…</p></div></details>
</section>
```
`.overview`, `.movers`, `.card` share the panel look (`.card` = one state card, title in UI 17px/650, not display).
Sub-headings inside a card: `<h3>` (UI 15px/600). Inside a card do not nest bordered boxes; use whitespace or a
`--line` rule.

**Picker bar above a tab's sections**: `<div class="tbar">` holding the date picker, selects and `.smooth` checkbox;
`<span class="tlabel">` for a short muted note (13px). Long scope notes do not belong in the bar: move them into the
first section's `details.about` or keep one short sentence.

**Disclosure — `details.about`** (new). Closed by default; the summary is a quiet text button with a CSS chevron
(no glyph), ink-2 600 14px, accent on hover/open. Body is 14px ink-2, line-height 1.6, max `--read`.
```html
<details class="about">
  <summary>How this is calculated</summary>     <!-- or "About this data", "How to read this chart" -->
  <div class="about-body">
    <p>…</p>
    <h4>Status</h4>                            <!-- optional sub-heads inside long notes -->
    <dl><dt>Missing demand</dt><dd>Our clicks fell below 0.6× of search demand.</dd></dl>
    <ul><li>…</li></ul>
  </div>
</details>
```
Use it for: method notes, definitions, "how to read" text, caveats, footers (`.tabnotes`/`footer.notes` content
moves into one or more of these). Put it at the end of the section it explains (or one at the end of the tab for
page-wide method notes). Keep `.tabnotes` only as a wrapper for those disclosures.

**Buttons and chips — `.lg`.** Pill, 34px min height, paper fill, `--control-border`, 14px/500. Legend chips put the
series swatch (from `legendSwatch()`) first. Toggle-off state: `.lg.off` (transparent, dashed edge, muted text, faded
swatch) + `aria-pressed="false"`. A `details.pop > summary.lg` turns accent-soft while open.

**Selects.** Add `class="sel"` to any new `<select>` (already styled: `.statef`, `.card h2 .msel`, `.qhead select`,
`.movers .mhead select`, `.popbody select`). Pill edge, token-drawn chevron, 14px. Don't add a ▾ glyph.

**Checkbox** `.smooth` label: `<label class="smooth"><input type="checkbox" id="…"> 7-day smoothing</label>`.

**Popover — `details.pop`** (`.pop-r` anchors right). Body `.popbody`: paper, `--border`, radius 12, `--shadow-pop`.
Rows `.prow`. Closes on outside click / Escape (global handler).

**Date-range picker** — `makeRangePicker(host, opts)` (shared JS). Presets left (active = accent-soft), two calendars
(selected day = solid accent, range = accent-soft). Label in the button: preset name bold + muted dates. Don't restyle.

**Tables — `table.mtab`.** 14px, tabular figures, header 13px/600 ink-2 sentence case with a `--border` rule below,
rows 9px vertical padding with `--line` hairlines, hover `--chip-bg`. Classes: `th.l`/left cells, `td.mn` (row name,
600), `td.rk` (rank, muted), `td.kw`/`td.dim` (secondary text), `td.ab` (abbr), `.up`/`.dn` (good/bad deltas, 600,
always with ↑/↓), `.lbl` (inline muted unit), `tr.mrow` (clickable row), `td.stcell` (holds pills).
Wrap wide tables: `<div style="overflow-x:auto">` or an existing wrapper class with `overflow-x: auto`.
Summary/total row: `--surface-2` background + 600 weight (see `.sttab tr.nat`, switch its `--chip-bg` to `--surface-2`).
Plain data tables (chart "Data table" views) use bare `<table>` inside `.tblwrap`.

**Status pills — `.pill`** + one of: `st-out` (good: "Outperforming", "Capturing"), `st-miss` (bad: "Missing demand",
"Not capturing", "Page 2+"), `st-track` (neutral: "Tracking", "New demand"), `st-low` (dashed outline + hollow dot:
"Low signal", "Old page"). Soft tint + darker text + a 6px dot drawn by CSS. Labels in sentence case.

**Hover readout — `#tip`.** Paper, radius 10, `--shadow-pop`, 13px. First line `.d` (14px/600: what + when).
Rows: `.row > .n` (swatch + name, ink-2) and `.v` (value, ink 600, tabular). Tables inside: `table.tt` (header 12px/600
muted with a `--line` rule; no row borders; `td.n` left name column; `.pos` good, `.zero` muted). Notes: `.tnote` (muted 12.5px).

**Empty state — `.mempty`**: muted 14px, 12px vertical padding, one plain sentence saying why there's nothing and what
would make something appear.

**Focus**: every interactive element shows `outline: 2px solid var(--accent)` on `:focus-visible`.

---

## 6. Copy rules

- Plain, short, active voice, from the reader's side: "Missing demand", "Search traffic", "Shown less than usual",
  not "miss", "GSC impr ratio", "vis gap".
- One sentence under each section heading saying what it answers. Everything longer goes in `details.about`.
- No em-dash asides, no "not X but Y", no scare quotes, no "worth noting". Prefer two short sentences.
- Fewer `·` chains: at most one `·` between two short facts; otherwise use separate labels or a line break.
- No decorative glyphs: no "ⓘ", "⚙", "▸". `▾` only on a real dropdown button (and not on `<select>`s, which have their
  own chevron). Arrows ↑ ↓ → are fine where they carry meaning (deltas, "search → clicks").
- Sentence case for every label, header, button, chip, pill and tab content heading.
- Spell out abbreviations on first use in a section ("Search Console (GSC)") or avoid them; "GSC" alone is jargon.
- Numbers keep their exact formatting and values. Don't round differently or drop units.

---

## 7. Chart rules (SVG drawn in JS)

- **Text**: tick labels `font-size="11.5"` `fill="var(--muted)"`; axis titles 11px weight 600 `var(--muted)`, sentence
  case ("Index", "Position", "CTR"); direct labels 11.5px weight 600 `var(--ink-2)`. No chart text below 10px.
  Text never wears the series color; identity comes from the swatch/mark beside it.
  Halo: `.chart svg text` and `.quad svg text` get a 3px paper halo (`paint-order: stroke`); for other charts add
  `class="halo"` to labels that can be crossed by lines, and draw those labels after the lines.
- **Gridlines** `stroke="var(--grid)"` 1px solid; the zero/baseline and reference lines (e.g. "typical = 1×")
  `var(--axis)` 1px (a reference line may be dashed `4 4`). Never dashed gridlines.
- **Lines**: primary series 2px; secondary series 1.75px; dotted/dashed reference series 1.5-2px; ghost/comparison
  series (last year) 1.25px at opacity .35. `stroke-linejoin="round" stroke-linecap="round"`. No opacity on primary lines.
- **Area**: only traffic gets an area (`var(--traffic-fill)`, ≈12% wash).
- **Markers/end dots**: r ≥ 4 with a 2px `var(--surface)` ring (`stroke="var(--surface)" stroke-width="2"`).
- **Crosshair** on hover: 1px `var(--ink-2)` dashed `3 3`.
- **Status marks in charts** use the shared helper `statusMark(status, cx, cy)` (global in build_dashboard.py):
  good = filled `--good` dot, missing demand = filled `--bad` down-triangle, tracking/low = hollow `--neutral` ring.
- **Legend**: ≥ 2 series always have a legend (chips or a `.hlg`-style inline legend: 22×12 swatch + 13px ink-2
  label); a single series needs none (the title names it). Swatches come from `legendSwatch()` so dashes match.
- **Right-hand axes** are titled; their tick labels are muted (not series-colored).
- One scale per axis, labels only at values the axis reaches; keep labels inside the viewBox.
- Plot area sits directly on the card (`--surface`); no extra chart borders or backgrounds.

---

## 8. Notes for the next agents

Overview agent (build_dashboard.py):
- Already done in the foundation: tokens, fonts, all shared components, state-card chart text sizes/weights/colors,
  quadrant tokens + `statusMark`, header lede. Literal colors are gone from the file.
- Still yours: section order and copy; `footer.notes`, `#howto` and the long `.qnote` paragraphs into `details.about`;
  "Overview — SEO health" (em dash), "ⓘ How to Read", "⚙ Settings", "GSC …" chip labels, Title Case strings in JS
  (e.g. "Missing Demand", "Last 90 Days", "Our Traffic", "7-Day Smooth", "More Terms"), header strings like
  "why · our read of Search Console"; the howto/footer color names (see §2); `.mtab.score` status column alignment.

States tab (tabs/states.*) and Health tabs (tabs/health.*):
- Remove `font-family: "IBM Plex Sans"…` (health.css `#tip table.tt .u`) and `font-family="IBM Plex …"` attributes
  (health.js chart text); bump chart text from 9.5/10 to the §7 sizes.
- Raise tiny sizes: `.sttab th` phone 9.5px/9px → 12px; `.hch h3` 13px → `var(--fs-h3)`; `.hlg`, `.hsub`, `.hnote`,
  `.htcap`, `.htop`, `.stkw` 11.5px → 13px; `.hempty` 12px → 14px with `--surface-2` background.
- `.sttab tr.nat` and `.sttab tr.nat:hover` use `--surface-2` / `--chip-bg` instead of `--grid`.
- Use `--accent` (not `--fm`) for new focus rings. Use `class="sel"` on new selects.
- Move `.tabnotes` paragraphs and long `.psub` text into `details.about`.
