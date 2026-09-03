"""Fetch Google Trends daily interest for the fire keywords per state (or metro).

Usage: fetch_trends.py [state|national|metro] [year]
  state    (default) geo=US-{abbr}, queries originating in-state -> trends_data.json
  national geo=US -> trends_data_national.json
  metro    geo per metros.json entry -> trends_data_metro.json
  year     default 2026; e.g. 2025 -> trends_data_2025[.._national].json

Keywords (KWV 2): wildfire {name}, wildfire {abbr}, fire {name}, fire {abbr},
fire map {name}, fire map {abbr}, fire near me — and, metro mode only,
fire near {city} (the metro's biggest city).

Window: Feb 26 of the year through "today" shifted into that year. Google caps
comparisons at 5 terms and normalizes each request to its own max, so per job:
batch A = first 5 keywords, batch B = anchor ("fire {name}") + the remaining
keywords, each rescaled onto A's scale via the anchor ratio. Progress is saved
after every job (resumable); a stored file with a different timeframe or
keyword version is wiped and refetched. A geo Google rejects outright is
skipped with a warning instead of killing the run.
"""
import datetime, json, os, random, sys, time

from pytrends.request import TrendReq
from pytrends import exceptions as ptx
from metros import METROS, STATE_ABBR

KWV = 2  # keyword-set version; bump when the keyword templates change

MODE = sys.argv[1] if len(sys.argv) > 1 else "state"
assert MODE in ("state", "national", "metro"), MODE
YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 2026

_today = datetime.date.today()
_end = _today.replace(year=YEAR) if _today.year != YEAR else _today
TIMEFRAME = f"{YEAR}-02-26 {_end.isoformat()}"

_suffix = "" if YEAR == 2026 else f"_{YEAR}"
_name = {"state": f"trends_data{_suffix}.json",
         "national": f"trends_data{_suffix}_national.json",
         "metro": f"trends_data{_suffix}_metro.json"}[MODE]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), _name)

def keywords(state, city=None):
    n = state.replace("_", " ").replace("-", " ")
    a = STATE_ABBR[state].lower()
    kws = [f"wildfire {n}", f"wildfire {a}", f"fire {n}", f"fire {a}",
           f"fire map {n}", f"fire map {a}", "fire near me"]
    if city:
        kws.append(f"fire near {city}")
    return kws

# jobs: (job_key, state_name, geo, label, city)
jobs = []
if MODE == "metro":
    for state, metros in METROS.items():
        for m in metros:
            jobs.append((f"{state}/{m['key']}", state, m["geo"], m["name"], m["city"]))
else:
    for state in STATE_ABBR:
        geo = f"US-{STATE_ABBR[state]}" if MODE == "state" else "US"
        jobs.append((state, state, geo, state, None))

class SkipJob(Exception):
    pass

def fetch_batch(pt, kws, geo, attempt=0):
    try:
        pt.build_payload(kws, timeframe=TIMEFRAME, geo=geo)
        return pt.interest_over_time()
    except ptx.TooManyRequestsError:
        if attempt >= 5:
            raise
        wait = min(300, (2 ** attempt) * 20) + random.uniform(0, 10)
        print(f"    429, retrying in {wait:.0f}s", flush=True)
        time.sleep(wait)
        return fetch_batch(pt, kws, geo, attempt + 1)
    except ptx.ResponseError as e:
        # a 400 means Google rejects the geo/keywords — no point retrying
        raise SkipJob(str(e)[:150])
    except Exception as e:
        if attempt >= 3:
            raise
        wait = 20 * (attempt + 1)
        print(f"    error ({type(e).__name__}: {str(e)[:120]}), retrying in {wait}s", flush=True)
        time.sleep(wait)
        return fetch_batch(pt, kws, geo, attempt + 1)

def main():
    data = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            data = json.load(f)
    meta = data.get("meta", {})
    if meta and (meta.get("timeframe") != TIMEFRAME or meta.get("kwv") != KWV):
        print(f"stored meta {meta.get('timeframe')}/kwv{meta.get('kwv')} != "
              f"{TIMEFRAME}/kwv{KWV}; starting fresh", flush=True)
        data = {}

    pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
    skipped = []

    for job_key, state, geo, label, city in jobs:
        if job_key in data.get("states", {}):
            print(f"{job_key}: already fetched, skipping", flush=True)
            continue
        kws = keywords(state, city)
        anchor = kws[2]  # "fire {name}", present in both batches
        batch_a, batch_b = kws[:5], [anchor] + kws[5:]

        try:
            print(f"{job_key}: geo {geo} batch A {batch_a}", flush=True)
            df_a = fetch_batch(pt, batch_a, geo)
            time.sleep(8 + random.uniform(0, 6))
            print(f"{job_key}: batch B {batch_b}", flush=True)
            df_b = fetch_batch(pt, batch_b, geo)
        except SkipJob as e:
            print(f"  SKIPPED {job_key} ({geo}): {e}", flush=True)
            skipped.append(job_key)
            time.sleep(5)
            continue

        dates = [d.strftime("%Y-%m-%d") for d in df_a.index] if not df_a.empty else []
        series = {}
        for kw in batch_a:
            series[kw] = [int(v) for v in df_a[kw]] if not df_a.empty else []
        if not df_b.empty:
            a_anchor = sum(series.get(anchor, [])) or 0
            b_anchor = int(df_b[anchor].sum())
            ratio = (a_anchor / b_anchor) if b_anchor > 0 else 1.0
            for kw in kws[5:]:
                series[kw] = [round(float(v) * ratio, 2) for v in df_b[kw]]
        else:
            for kw in kws[5:]:
                series[kw] = []

        data.setdefault("meta", {
            "timeframe": TIMEFRAME, "mode": MODE, "kwv": KWV,
            "anchor_note": "keywords beyond the first five rescaled onto batch-A scale via shared anchor 'fire {state}'",
        })
        data.setdefault("states", {})[job_key] = {
            "abbr": STATE_ABBR[state], "label": label, "dates": dates,
            "keywords": kws, "series": series,
        }
        with open(OUT, "w") as f:
            json.dump(data, f)
        print(f"  saved {job_key}: {len(dates)} days", flush=True)
        time.sleep(10 + random.uniform(0, 8))

    print(f"DONE {MODE} {YEAR}. jobs: {len(data.get('states', {}))}"
          + (f", skipped: {skipped}" if skipped else ""), flush=True)

if __name__ == "__main__":
    main()
