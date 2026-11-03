"""Generate maps.json: per-state SVG path geometry for the metro choropleth.

For each dashboard state: clip every listed metro's Nielsen DMA polygon
(nielsentopo.json) to the state boundary (Census cb_2023_us_state_20m),
simplify, project (equirectangular with cos-latitude correction), and emit
compact SVG path strings. The dashboard ships only these paths — no geo data
or projection code reaches the page.
"""
import json, math, os

import shapefile  # pyshp
from shapely.geometry import shape as shp_shape, LineString, MultiPolygon, Polygon
from shapely.ops import unary_union, transform
import numpy as np

from metros import METROS, STATE_ABBR

BASE = os.path.dirname(os.path.abspath(__file__))
W = 420.0          # viewBox width per state map
SIMPLIFY = 0.02    # degrees; ~2km — plenty for a card-sized map
SLIVER = 0.08      # degrees (~8km); leftover strips narrower than this join the metro beside them (see below)

# ---- decode TopoJSON ----
topo = json.load(open(os.path.join(BASE, "nielsentopo.json")))
tsc, ttr = topo["transform"]["scale"], topo["transform"]["translate"]

def decode_arc(arc):
    pts, x, y = [], 0, 0
    for dx, dy in arc:
        x += dx
        y += dy
        pts.append((x * tsc[0] + ttr[0], y * tsc[1] + ttr[1]))
    return pts

def simplify_arc(pts):
    """Simplify each shared arc once (ends kept), so neighbouring DMAs keep identical borders.
    Simplifying each clipped DMA on its own left slivers between metros and along the state edge."""
    if len(pts) <= 2:
        return pts
    s = list(LineString(pts).simplify(SIMPLIFY).coords)
    return s if len(s) >= (4 if pts[0] == pts[-1] else 2) else pts

ARCS = [simplify_arc(decode_arc(a)) for a in topo["arcs"]]

def ring_coords(arc_idxs):
    out = []
    for i in arc_idxs:
        pts = ARCS[i] if i >= 0 else ARCS[~i][::-1]
        if out and out[-1] == pts[0]:
            pts = pts[1:]
        out.extend(pts)
    return out

def geom_to_shape(g):
    def poly(rings):
        rr = [ring_coords(r) for r in rings]
        rr = [r for r in rr if len(r) >= 4]
        if not rr:
            return None
        return Polygon(rr[0], rr[1:])
    if g["type"] == "Polygon":
        p = poly(g["arcs"])
        return p
    if g["type"] == "MultiPolygon":
        ps = [poly(rings) for rings in g["arcs"]]
        ps = [p for p in ps if p is not None]
        return MultiPolygon(ps) if ps else None
    return None

dma_shapes = {}
for g in topo["objects"]["nielsen_dma"]["geometries"]:
    dma = g["properties"]["dma"]
    s = geom_to_shape(g)
    if s is not None and not s.is_empty:
        dma_shapes[dma] = s.buffer(0)  # heal any self-intersections
print(f"decoded {len(dma_shapes)} DMA shapes")

# ---- state boundaries ----
sf = shapefile.Reader(os.path.join(BASE, "cb_states", "cb_2023_us_state_20m"))
fields = [f[0] for f in sf.fields[1:]]
state_shapes = {}
for sr in sf.shapeRecords():
    rec = dict(zip(fields, sr.record))
    state_shapes[rec["STUSPS"]] = shp_shape(sr.shape.__geo_interface__).buffer(0)
# Alaska's Aleutians cross the 180th meridian: put them at -180..-190 so the state projects in one piece
state_shapes["AK"] = transform(lambda x, y: (np.where(np.asarray(x) > 0, np.asarray(x) - 360, x), y), state_shapes["AK"])
# DMAs that are a whole state but absent from the lower-48 Nielsen TopoJSON (Honolulu = all of Hawaii)
WHOLE_STATE_DMA = {744: "HI"}
for dma, ab in WHOLE_STATE_DMA.items():
    dma_shapes.setdefault(dma, state_shapes[ab])

ALL_DMAS = unary_union(list(dma_shapes.values()))

def polys_of(g):
    return [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and not p.is_empty]

def to_path(geom, project):
    """Multipolygon -> compact SVG path string."""
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    parts = []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            pts = [project(x, y) for x, y in ring.coords]
            d = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts[:-1]) + "Z"
            parts.append(d)
    return "".join(parts)

out = {}
for state, abbr in STATE_ABBR.items():
    # metros are clipped to this same simplified outline, so their edges land exactly on the drawn border
    st_shape = state_shapes[abbr].simplify(SIMPLIFY).buffer(0)
    minx, miny, maxx, maxy = st_shape.bounds
    lat_mid = (miny + maxy) / 2
    kx = math.cos(math.radians(lat_mid))
    spanx, spany = (maxx - minx) * kx, (maxy - miny)
    scale = W / spanx
    H = round(spany * scale, 1)
    def project(lon, lat, minx=minx, maxy=maxy, kx=kx, scale=scale):
        return ((lon - minx) * kx * scale, (maxy - lat) * scale)

    metros_geom = {}
    for m in METROS.get(state, []):
        dma = dma_shapes.get(m["dma"])
        if dma is None:
            print(f"  {state}/{m['key']}: DMA {m['dma']} missing from topo")
            continue
        inter = dma.intersection(st_shape)
        if inter.is_empty:
            print(f"  {state}/{m['key']}: no overlap with state, skipped on map")
            continue
        if inter.is_empty or inter.geom_type not in ("Polygon", "MultiPolygon"):
            inter = unary_union([g for g in getattr(inter, "geoms", [inter])
                                 if g.geom_type in ("Polygon", "MultiPolygon")])
            if inter.is_empty:
                continue
        metros_geom[m["key"]] = inter

    # Nielsen's coastlines and state borders are coarser than the Census outline, so parts of the state end up in
    # no DMA (bays, islands, coasts) or in a thin strip of a neighbouring state's DMA (borders). Land in no DMA goes
    # to the nearest DMA, and joins that metro if it's listed; an unlisted-DMA piece narrower than SLIVER joins the
    # listed metro it shares the most edge with (real unlisted markets are far wider).
    if metros_geom:
        near = {d: g for d, g in dma_shapes.items() if g.distance(st_shape) < SLIVER}
        key_of = {m["dma"]: m["key"] for m in METROS.get(state, []) if m["key"] in metros_geom}
        for piece in polys_of(st_shape.difference(ALL_DMAS)):
            d = min(near, key=lambda d: near[d].distance(piece) - piece.boundary.intersection(near[d].buffer(1e-7)).length)
            if d in key_of:
                metros_geom[key_of[d]] = metros_geom[key_of[d]].union(piece)
        for piece in polys_of(st_shape.difference(unary_union(list(metros_geom.values())))):
            if not piece.buffer(-SLIVER / 2).is_empty:
                continue
            edge = {k: piece.boundary.intersection(g.buffer(1e-7)).length for k, g in metros_geom.items()}
            k = max(edge, key=edge.get)
            if edge[k] > 0:
                metros_geom[k] = metros_geom[k].union(piece)
        # a sub-metre close fuses pieces that touch along a line, which would otherwise draw as a hairline
        metros_geom = {k: g.buffer(1e-6, join_style=2).buffer(-1e-6, join_style=2) for k, g in metros_geom.items()}
    metros_paths = {k: to_path(g, project) for k, g in metros_geom.items()}

    covered = unary_union(list(metros_geom.values())) if metros_geom else Polygon()
    gap = (st_shape.area - covered.area) / st_shape.area > 0.02

    out[state] = {"w": W, "h": H, "gap": gap,
                  "outline": to_path(st_shape, project),
                  # client-side projection for point overlays: x=(lon-minx)*kx, y=(maxy-lat)*ky
                  "proj": {"minx": round(minx, 6), "maxy": round(maxy, 6),
                           "kx": round(kx * scale, 6), "ky": round(scale, 6)},
                  "metros": metros_paths}
    print(f"{state:<14} {len(metros_paths)}/{len(METROS.get(state, []))} metros mapped, h={H}")

with open(os.path.join(BASE, "maps.json"), "w") as f:
    json.dump(out, f)
size = os.path.getsize(os.path.join(BASE, "maps.json"))
print(f"wrote maps.json ({size//1024} KB)")
