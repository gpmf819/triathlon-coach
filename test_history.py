from dotenv import load_dotenv
load_dotenv()

from intervals_client import get_headers
from datetime import datetime
import requests
import statistics
from collections import defaultdict

cfg = get_headers()

r = requests.get(
    f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities",
    headers=cfg["headers"],
    params={
        "oldest": "2025-02-01",
        "newest": "2025-06-30",
        "fields": "id,type,start_date_local,name,moving_time,icu_weighted_avg_watts,icu_training_load,icu_intensity,trainer"
    }
)

all_acts = r.json()

# Filter to CoachChris trainer rides with power
window2 = []
for a in all_acts:
    date = datetime.fromisoformat(a["start_date_local"][:10])
    is_feb_jun_2025 = date.year == 2025 and date.month in [2, 3, 4, 5, 6]
    has_coachchris = "CoachChris" in a.get("name", "")
    has_power = bool(a.get("icu_weighted_avg_watts"))
    is_trainer = a.get("trainer") is True
    is_indoor = a.get("type") in ["VirtualRide", "Ride"]
    if is_feb_jun_2025 and has_coachchris and has_power and is_trainer and is_indoor:
        window2.append(a)

print(f"CoachChris rides found: {len(window2)}")

# Strip route suffix to get canonical workout name
def canonical_name(name):
    # Remove "Zwift - " prefix
    name = name.replace("Zwift - ", "").strip()
    # Strip " on <Route> in <World>" suffix
    if " on " in name:
        name = name[:name.rfind(" on ")]
    # Strip trailing " in <World>" suffix (e.g. "in Watopia", "in Makuri Islands")
    import re
    name = re.sub(r'\s+in\s+(Watopia|Makuri Islands|France|London|New York|Innsbruck)$', '', name).strip()
    return name

# Group by canonical name
def classify_zone(if_val):
    if if_val < 0.68:
        return "Z2 Endurance"
    elif if_val < 0.84:
        return "Tempo / Sweet Spot"
    elif if_val < 0.97:
        return "Threshold"
    else:
        return "VO2max+"

by_name = defaultdict(list)
for a in window2:
    np = a["icu_weighted_avg_watts"]
    canon = canonical_name(a["name"])
    by_name[canon].append({
        "np": np,
        "if_val": round(np / 291, 2),
        "tss": a.get("icu_training_load") or 0,
        "duration_min": (a.get("moving_time") or 0) // 60,
        "date": a["start_date_local"][:10]
    })

# Build library
library = []
for name, sessions in by_name.items():
    ifs = [s["if_val"] for s in sessions]
    median_if = round(statistics.median(ifs), 2)
    library.append({
        "name": name,
        "executions": len(sessions),
        "median_np": round(statistics.median([s["np"] for s in sessions])),
        "median_if": median_if,
        "median_tss": round(statistics.median([s["tss"] for s in sessions])),
        "median_duration_min": round(statistics.median([s["duration_min"] for s in sessions])),
        "zone": classify_zone(median_if)
    })

library.sort(key=lambda x: x["median_if"])

print(f"Unique canonical workouts: {len(library)}\n")
for w in library:
    execs = f"x{w['executions']}" if w['executions'] > 1 else "x1"
    print(f"{w['zone']:25} | IF {w['median_if']} | NP {w['median_np']}W | TSS {w['median_tss']} | {w['median_duration_min']}min | {execs} | {w['name']}")