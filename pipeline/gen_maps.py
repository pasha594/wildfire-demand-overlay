"""Generate maps.json: per-state SVG path geometry for the metro choropleth.

For each dashboard state: clip every listed metro's Nielsen DMA polygon
(nielsentopo.json) to the state boundary (Census cb_2023_us_state_20m),
simplify, project (equirectangular with cos-latitude correction), and emit
compact SVG path strings. The dashboard ships only these paths — no geo data
or projection code reaches the page.
"""
import json, math, os

import shapefile  # pyshp
from shapely.geometry import shape as shp_shape, MultiPolygon, Polygon
from shapely.ops import unary_union

from metros import METROS, STATE_ABBR

BASE = os.path.dirname(os.path.abspath(__file__))
W = 420.0          # viewBox width per state map
SIMPLIFY = 0.02    # degrees; ~2km — plenty for a card-sized map

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

ARCS = [decode_arc(a) for a in topo["arcs"]]

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
    st_shape = state_shapes[abbr].simplify(SIMPLIFY)
    minx, miny, maxx, maxy = st_shape.bounds
    lat_mid = (miny + maxy) / 2
    kx = math.cos(math.radians(lat_mid))
    spanx, spany = (maxx - minx) * kx, (maxy - miny)
    scale = W / spanx
    H = round(spany * scale, 1)
    def project(lon, lat, minx=minx, maxy=maxy, kx=kx, scale=scale):
        return ((lon - minx) * kx * scale, (maxy - lat) * scale)

    metros_paths = {}
    for m in METROS.get(state, []):
        dma = dma_shapes.get(m["dma"])
        if dma is None:
            print(f"  {state}/{m['key']}: DMA {m['dma']} missing from topo")
            continue
        inter = dma.intersection(state_shapes[abbr])
        if inter.is_empty:
            print(f"  {state}/{m['key']}: no overlap with state, skipped on map")
            continue
        inter = inter.simplify(SIMPLIFY).buffer(0)
        if inter.is_empty or inter.geom_type not in ("Polygon", "MultiPolygon"):
            inter = unary_union([g for g in getattr(inter, "geoms", [inter])
                                 if g.geom_type in ("Polygon", "MultiPolygon")])
            if inter.is_empty:
                continue
        metros_paths[m["key"]] = to_path(inter, project)

    covered = unary_union([dma_shapes[m["dma"]].intersection(state_shapes[abbr])
                           for m in METROS.get(state, []) if m["dma"] in dma_shapes])
    gap = (state_shapes[abbr].area - covered.area) / state_shapes[abbr].area > 0.02

    out[state] = {"w": W, "h": H, "gap": gap,
                  "outline": to_path(st_shape if st_shape.geom_type in ("Polygon", "MultiPolygon") else st_shape.buffer(0), project),
                  # client-side projection for point overlays: x=(lon-minx)*kx, y=(maxy-lat)*ky
                  "proj": {"minx": round(minx, 6), "maxy": round(maxy, 6),
                           "kx": round(kx * scale, 6), "ky": round(scale, 6)},
                  "metros": metros_paths}
    print(f"{state:<14} {len(metros_paths)}/{len(METROS.get(state, []))} metros mapped, h={H}")

with open(os.path.join(BASE, "maps.json"), "w") as f:
    json.dump(out, f)
size = os.path.getsize(os.path.join(BASE, "maps.json"))
print(f"wrote maps.json ({size//1024} KB)")
