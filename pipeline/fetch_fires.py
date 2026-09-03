"""Fetch fire milestones from fire-api-dev.web.app for the dashboard states.

Filters: wildfire only (no prescribed burns), >100 acres, created within the
dashboard window. Saves fires.json keyed by dashboard state key.
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
                "filters": "fire_type=wildfire, acres>100, created within window",
                "window": f"{WINDOW_START.date()}..{WINDOW_END_DATE}"},
       "states": {}}

epoch = int(WINDOW_START.timestamp())
for key, code in STATES:
    fires, offset = [], 0
    while True:
        d = get(state=code, fire_type="wildfire", acres=">100",
                created_on=f">={epoch}", active="all",
                sort_by="created_on", sort_direction="asc",
                limit=100, offset=offset)
        for f in d["fires"]:
            date = (f.get("created_on") or "")[:10]
            if not date or date > WINDOW_END_DATE:
                continue
            fires.append({
                "t": f.get("post_title") or "(unnamed)",
                "d": date,
                "a": f.get("acres"),
                "slug": f.get("unique_slug"),
                "coords": f.get("fire_coordinates"),
                "county": f.get("county"),
                "city": f.get("city"),
                "active": bool(f.get("active")),
                "containment": f.get("containment"),
            })
        total = d["pagination"]["total"]
        offset += len(d["fires"])
        if offset >= total or not d["fires"]:
            break
    out["states"][key] = fires
    print(f"{key:<14} {len(fires)} fires", flush=True)

with open(OUT, "w") as f:
    json.dump(out, f)
print("wrote", OUT)
