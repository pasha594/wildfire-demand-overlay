"""Fetch fire milestones from fire-api-dev.web.app for the dashboard states.

Filters: wildfire only (no prescribed burns), created within the dashboard
window; >100 acres for the historical set, ANY acreage while a fire is active
(new starts report 0 acres until first sizing). Charts re-apply the >100ac
cut at render time; the state-map active markers use everything.
Saves fires.json keyed by dashboard state key.
"""
import json, os, urllib.request, urllib.parse, datetime, time

from metros import STATE_ABBR

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "fires.json")

WINDOW_START = datetime.datetime(2026, 2, 26, tzinfo=datetime.timezone.utc)
WINDOW_END_DATE = datetime.date.today().isoformat()

STATES = list(STATE_ABBR.items())

def get(**params):
    url = "https://fire-api-dev.web.app/fires?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 3:
                raise
            print(f"  retry after {type(e).__name__}", flush=True)
            time.sleep(5 * (attempt + 1))

out = {"meta": {"source": "https://fire-api-dev.web.app/fires",
                "filters": "fire_type=wildfire; acres>100 within window, plus currently-active fires of any acreage",
                "window": f"{WINDOW_START.date()}..{WINDOW_END_DATE}"},
       "states": {}}

epoch = int(WINDOW_START.timestamp())

def simplify(f, date):
    return {
        "t": f.get("post_title") or "(unnamed)",
        "d": date,
        "a": f.get("acres"),
        "slug": f.get("unique_slug"),
        "coords": f.get("fire_coordinates"),
        "county": f.get("county"),
        "city": f.get("city"),
        "active": bool(f.get("active")),
        "containment": f.get("containment"),
    }

def fetch_all(**params):
    fires, offset = [], 0
    while True:
        d = get(**params, limit=100, offset=offset)
        for f in d["fires"]:
            date = (f.get("created_on") or "")[:10]
            if not date or date > WINDOW_END_DATE:
                continue
            fires.append(simplify(f, date))
        total = d["pagination"]["total"]
        offset += len(d["fires"])
        if offset >= total or not d["fires"]:
            break
    return fires

for key, code in STATES:
    common = dict(state=code, fire_type="wildfire", created_on=f">={epoch}",
                  sort_by="created_on", sort_direction="asc")
    fires = fetch_all(acres=">100", active="all", **common)
    # New starts report 0 acres until first sizing, so an acreage filter hides
    # exactly the fires the "currently active" map markers exist to show.
    # Charts keep their >100ac semantics via an acreage check at render time.
    seen = {f["slug"] or (f["t"], f["d"]) for f in fires}
    added = [f for f in fetch_all(active="true", **common)
             if (f["slug"] or (f["t"], f["d"])) not in seen]
    fires.extend(added)
    fires.sort(key=lambda f: f["d"])
    out["states"][key] = fires
    note = f" (+{len(added)} active under-100ac/unsized)" if added else ""
    print(f"{key:<14} {len(fires)} fires{note}", flush=True)

with open(OUT, "w") as f:
    json.dump(out, f)
print("wrote", OUT)
