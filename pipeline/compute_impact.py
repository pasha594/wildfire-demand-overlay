"""Compute population-within-radius rings for every fire in fires.json.

For each fire and each ring R in RINGS (miles), counts 2020 Census population
whose block-group centroid lies within R + fire_radius miles of the fire's
start coordinates, where fire_radius = sqrt(acres / (640*pi)) approximates the
burn as a circle. Uses the national centroid file so state borders don't clip.
Writes the ring vector back into fires.json as "p" plus "fr" (fire radius, mi).
"""
import json, math, os
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
RINGS = [2, 3, 5, 7.5, 10, 15, 20]
EARTH_MI = 3958.8

# national block-group population centroids
lats, lons, pops = [], [], []
with open(os.path.join(BASE, "cenpop", "CenPop2020_Mean_BG.txt"), encoding="utf-8-sig") as f:
    next(f)
    for line in f:
        parts = line.strip().split(",")
        if len(parts) < 7:
            continue
        pops.append(float(parts[4]))
        lats.append(float(parts[5]))
        lons.append(float(parts[6]))
lat_a = np.radians(np.array(lats))
lon_a = np.radians(np.array(lons))
pop_a = np.array(pops)
print(f"loaded {len(pop_a):,} block groups, total pop {pop_a.sum()/1e6:.1f}M")

def pop_rings(lat, lon, fire_radius_mi):
    la, lo = math.radians(lat), math.radians(lon)
    # cheap bounding-box prefilter for the largest effective radius
    max_r = RINGS[-1] + fire_radius_mi
    dlat_max = max_r / 69.0 * 1.1
    dlon_max = max_r / (69.0 * max(0.2, math.cos(la))) * 1.1
    m = (np.abs(lat_a - la) < math.radians(dlat_max)) & (np.abs(lon_a - lo) < math.radians(dlon_max))
    if not m.any():
        return {str(r): 0 for r in RINGS}
    slat, slon, spop = lat_a[m], lon_a[m], pop_a[m]
    # haversine
    dlat, dlon = slat - la, slon - lo
    h = np.sin(dlat / 2) ** 2 + math.cos(la) * np.cos(slat) * np.sin(dlon / 2) ** 2
    d = 2 * EARTH_MI * np.arcsin(np.sqrt(h))
    return {str(r): int(spop[d <= r + fire_radius_mi].sum()) for r in RINGS}

path = os.path.join(BASE, "fires.json")
data = json.load(open(path))
n_done = n_nocoord = 0
for key, fires in data["states"].items():
    for f in fires:
        coords = f.get("coords")
        if not coords:
            f["p"], f["fr"] = None, None
            n_nocoord += 1
            continue
        try:
            lat, lon = (float(x) for x in coords.split(","))
        except ValueError:
            f["p"], f["fr"] = None, None
            n_nocoord += 1
            continue
        fr = math.sqrt((f.get("a") or 0) / (640 * math.pi))
        f["p"] = pop_rings(lat, lon, fr)
        f["fr"] = round(fr, 2)
        n_done += 1
    print(f"{key:<14} done", flush=True)

data["meta"]["impact"] = {
    "rings_mi": RINGS,
    "definition": "p[R] = 2020 Census population with block-group centroid within R + sqrt(acres/(640*pi)) miles of fire start",
    "source": "CenPop2020_Mean_BG.txt (national)",
}
json.dump(data, open(path, "w"))
print(f"computed rings for {n_done} fires ({n_nocoord} without usable coordinates)")

# calibration check on the user's known-eventful examples
for key, name in [("colorado", "Aspen Acres"), ("georgia", "Hwy 82"), ("utah", "Snyder")]:
    for f in data["states"][key]:
        if name.lower() in f["t"].lower():
            print(f"  {f['t']:<22} {key:<10} acres={f['a']:>7} fr={f['fr']}mi p={f['p']}")
