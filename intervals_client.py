import requests
import os
import re
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

RACE_DATE = date(2026, 6, 20)
CTL_RACE_TARGET = 48

PERIODIZATION = [
    {"phase": "Base 1",    "start": "2026-03-21", "end": "2026-03-27", "ctl_target": (25, 30),  "tss_target": (260, 290)},
    {"phase": "Base 2",    "start": "2026-03-28", "end": "2026-04-10", "ctl_target": (30, 35),  "tss_target": (290, 320)},
    {"phase": "Late Base", "start": "2026-04-11", "end": "2026-04-24", "ctl_target": (35, 40),  "tss_target": (320, 350)},
    {"phase": "Build 1",   "start": "2026-04-25", "end": "2026-05-08", "ctl_target": (40, 45),  "tss_target": (350, 380)},
    {"phase": "Build 2",   "start": "2026-05-09", "end": "2026-05-22", "ctl_target": (45, 50),  "tss_target": (380, 420)},
    {"phase": "Peak",      "start": "2026-05-23", "end": "2026-06-05", "ctl_target": (50, 52),  "tss_target": (400, 450)},
    {"phase": "Taper 1",   "start": "2026-06-06", "end": "2026-06-12", "ctl_target": (50, 52),  "tss_target": (200, 250)},
    {"phase": "Race Week", "start": "2026-06-13", "end": "2026-06-20", "ctl_target": (48, 50),  "tss_target": (100, 150)},
]

PHASE_DESCRIPTIONS = {
    "Base 1":    "Aerobic volume and Z2 foundation. Bike priority. Build consistency.",
    "Base 2":    "Aerobic volume and Z2 foundation. Bike > Run > Swim. Swim resumes April.",
    "Late Base": "Extended aerobic base, swim fully integrated. Volume building.",
    "Build 1":   "Threshold and race-specific intensity. Brick sessions introduced. All three sports active.",
    "Build 2":   "Race-pace intervals, high intensity. Olympic distance simulation.",
    "Peak":      "Race-pace intervals, Olympic distance bricks, high intensity. Volume tapering begins.",
    "Taper 1":   "Volume reduction, race sharpening, leg freshness priority.",
    "Race Week": "Activation only. Rest and sharpen. No new fitness gains.",
}


def get_current_phase_targets():
    """Return the current periodization phase dict based on today's date."""
    today = date.today().isoformat()
    for phase in PERIODIZATION:
        if phase["start"] <= today <= phase["end"]:
            return phase
    # Before season starts → return first phase; after season ends → last phase
    if today < PERIODIZATION[0]["start"]:
        return PERIODIZATION[0]
    return PERIODIZATION[-1]


def get_headers():
    api_key = os.getenv("INTERVALS_API_KEY")
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    return {
        "base_url": "https://intervals.icu/api/v1",
        "athlete_id": athlete_id,
        "headers": {
            "Authorization": f"Basic {requests.auth._basic_auth_str('API_KEY', api_key).split(' ')[1]}"
        }
    }


def get_headers():
    import base64
    api_key = os.getenv("INTERVALS_API_KEY")
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    return {
        "base_url": "https://intervals.icu/api/v1",
        "athlete_id": athlete_id,
        "headers": {
            "Authorization": f"Basic {token}"
        }
    }


def get_fitness_data():
    cfg = get_headers()
    today = (date.today() + timedelta(days=1)).isoformat()  # exclusive upper bound
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    # Wellness (CTL/ATL/TSB)
    wellness_url = f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/wellness"
    wellness = requests.get(
        wellness_url,
        headers=cfg["headers"],
        params={"oldest": week_ago, "newest": today}
    )
    wellness.raise_for_status()

    # Activities with extended fields
    activities_url = f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities"
    activities = requests.get(
        activities_url,
        headers=cfg["headers"],
        params={
            "oldest": week_ago,
            "newest": today,
            "fields": "id,type,name,start_date_local,moving_time,distance,average_heartrate,max_heartrate,average_watts,normalized_power,intensity_factor,tss,average_speed,suffer_score,icu_weighted_avg_watts,icu_training_load,icu_intensity,trainer"
        }
    )
    activities.raise_for_status()
    acts = activities.json()

    # For bike activities, fetch full detail to get power data
    bike_types = ["Ride", "VirtualRide", "MountainBikeRide", "GravelRide"]
    enriched = []
    for act in acts:
        if act.get("type") in bike_types and act.get("id"):
            try:
                detail = requests.get(
                    f"{cfg['base_url']}/activity/{act['id']}",
                    headers=cfg["headers"]
                ).json()
                act["average_watts"] = detail.get("icu_average_watts")
                act["normalized_power"] = detail.get("icu_weighted_avg_watts")
                act["intensity_factor"] = round(detail.get("icu_intensity", 0) / 100, 2) if detail.get("icu_intensity") else None
                act["tss"] = detail.get("icu_training_load")
            except Exception:
                pass
        enriched.append(act)

    return {
        "wellness": wellness.json(),
        "recent_activities": enriched
    }


def get_athlete_profile():
    cfg = get_headers()
    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}",
        headers=cfg["headers"]
    )
    r.raise_for_status()
    return r.json()


def summarize_athlete_profile(profile):
    """Extract key athlete metrics from the Intervals.icu athlete profile."""

    def get_zone_values(zones_list):
        if not zones_list:
            return []
        return [z.get("max") or z.get("min") for z in zones_list if z]

    # Bike settings
    bike = next((s for s in profile.get("sportSettings", []) if s.get("type") == "Ride"), {})
    bike_hr_zones = [z["max"] for z in bike.get("hrZones", []) if z.get("max")] if bike.get("hrZones") else []
    bike_power_zones_raw = bike.get("powerZones", [])
    bike_power_zone_names = [z.get("name", f"Z{i+1}") for i, z in enumerate(bike_power_zones_raw)]
    bike_power_zones = [round(291 * (z.get("max", 0) / 100)) for z in bike_power_zones_raw if z.get("max")]

    # Run settings
    run = next((s for s in profile.get("sportSettings", []) if s.get("type") == "Run"), {})
    run_hr_zones = [z["max"] for z in run.get("hrZones", []) if z.get("max")] if run.get("hrZones") else []

    # Swim settings
    swim = next((s for s in profile.get("sportSettings", []) if s.get("type") == "Swim"), {})
    swim_threshold = swim.get("thresholdPace")

    return {
        "resting_hr": profile.get("restingHR"),
        "max_hr": profile.get("maxHR"),
        "weight_kg": profile.get("weight"),
        "bike": {
            "ftp": 291,  # confirmed ramp test, overrides Intervals.icu value of 270
            "lthr": bike.get("lthr") or 172,
            "max_hr": bike.get("maxHR") or 190,
            "hr_zones": bike_hr_zones,
            "power_zone_names": bike_power_zone_names,
            "power_zones": bike_power_zones,
        },
        "run": {
            "lthr": run.get("lthr") or 172,
            "hr_zones": run_hr_zones,
        },
        "swim": {
            "threshold_pace_per_100m": "2:00/100m",  # manually confirmed
        }
    }


def get_weekly_summary():
    cfg = get_headers()
    today = date.today()

    days_since_monday = today.weekday()
    week_start = (today - timedelta(days=days_since_monday)).isoformat()
    week_end = (today + timedelta(days=1)).isoformat()  # exclusive upper bound

    activities_url = f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities"
    activities = requests.get(
        activities_url,
        headers=cfg["headers"],
        params={
            "oldest": week_start,
            "newest": week_end,
            "fields": "id,type,moving_time,distance,icu_training_load,average_heartrate"
        }
    )
    activities.raise_for_status()
    acts = activities.json()

    summary = {
        "bike": {"count": 0, "duration_min": 0, "distance_km": 0, "tss": 0},
        "run": {"count": 0, "duration_min": 0, "distance_km": 0, "tss": 0},
        "swim": {"count": 0, "duration_min": 0, "distance_km": 0, "tss": 0},
        "other": {"count": 0, "duration_min": 0, "tss": 0},
    }

    bike_types = ["Ride", "VirtualRide", "MountainBikeRide", "GravelRide"]
    run_types = ["Run", "VirtualRun", "TrailRun"]
    swim_types = ["Swim", "OpenWaterSwim"]

    total_tss = 0
    for act in acts:
        duration = (act.get("moving_time") or 0) // 60
        distance = round((act.get("distance") or 0) / 1000, 1)
        tss = act.get("icu_training_load") or 0
        total_tss += tss
        t = act.get("type", "")

        if t in bike_types:
            summary["bike"]["count"] += 1
            summary["bike"]["duration_min"] += duration
            summary["bike"]["distance_km"] += distance
            summary["bike"]["tss"] += tss
        elif t in run_types:
            summary["run"]["count"] += 1
            summary["run"]["duration_min"] += duration
            summary["run"]["distance_km"] += distance
            summary["run"]["tss"] += tss
        elif t in swim_types:
            summary["swim"]["count"] += 1
            summary["swim"]["duration_min"] += duration
            summary["swim"]["distance_km"] += distance
            summary["swim"]["tss"] += tss
        else:
            summary["other"]["count"] += 1
            summary["other"]["duration_min"] += duration
            summary["other"]["tss"] += tss

    days_done = days_since_monday + 1
    days_remaining = 7 - days_done

    summary["total_tss"] = round(total_tss)
    summary["week_start"] = week_start
    summary["days_done"] = days_done
    summary["days_remaining"] = days_remaining

    return summary

def get_ctl_trajectory():
    """Get CTL trajectory (4-week and 12-week) plus year-over-year comparison."""
    cfg = get_headers()
    today = date.today()

    # Fetch 12 weeks back to cover both trajectory windows
    start_12w = (today - timedelta(weeks=12)).isoformat()
    end_today = today.isoformat()

    # Also fetch same ±1 week window for 2025 and 2024
    week_start = (today - timedelta(days=7))
    week_end = (today + timedelta(days=7))

    def fetch_wellness(oldest, newest):
        r = requests.get(
            f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/wellness",
            headers=cfg["headers"],
            params={"oldest": oldest, "newest": newest}
        )
        r.raise_for_status()
        return r.json()

    # Current year - 12 weeks of data
    current = fetch_wellness(start_12w, end_today)

    # 2025 same week
    y2025 = fetch_wellness(
        (week_start.replace(year=2025)).isoformat(),
        (week_end.replace(year=2025)).isoformat()
    )

    # 2024 same week
    y2024 = fetch_wellness(
        (week_start.replace(year=2024)).isoformat(),
        (week_end.replace(year=2024)).isoformat()
    )

    def extract_ctl(wellness_list):
        """Get CTL values with dates, filtering out nulls."""
        return [
            {"date": w["id"], "ctl": round(w["ctl"], 1)}
            for w in wellness_list
            if w.get("ctl") is not None
        ]

    def avg_ctl(wellness_list):
        """Get average CTL for a window."""
        values = [w["ctl"] for w in wellness_list if w.get("ctl") is not None]
        return round(sum(values) / len(values), 1) if values else None

    def weekly_ctl(wellness_list):
        """Summarize CTL by week - last value of each week."""
        from collections import OrderedDict
        by_week = OrderedDict()
        for w in wellness_list:
            if w.get("ctl") is None:
                continue
            d = datetime.fromisoformat(w["id"])
            week_key = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
            by_week[week_key] = round(w["ctl"], 1)
        return by_week

    all_ctl = extract_ctl(current)
    weekly = weekly_ctl(current)
    weeks = list(weekly.items())

    # 4-week trend (last 4 weekly values)
    trend_4w = weeks[-4:] if len(weeks) >= 4 else weeks

    # 12-week trend (all weekly values)
    trend_12w = weeks

    # Direction assessment
    def trend_direction(trend):
        if len(trend) < 2:
            return "insufficient data"
        delta = trend[-1][1] - trend[0][1]
        if delta > 5:
            return f"↑ building (+{round(delta, 1)})"
        elif delta < -5:
            return f"↓ declining ({round(delta, 1)})"
        else:
            return f"→ stable ({round(delta, 1):+})"

    # Race planning constants
    CTL_TARGET = CTL_RACE_TARGET  # 48 for Olympic distance
    weeks_to_race = (RACE_DATE - today).days // 7
    weeks_remaining_for_ctl = max(weeks_to_race - 2, 1)

    current_ctl = all_ctl[-1]["ctl"] if all_ctl else 0
    ctl_gap = round(CTL_TARGET - current_ctl, 1)
    ctl_per_week = round(ctl_gap / weeks_remaining_for_ctl, 1)

    current_phase = get_current_phase_targets()

    # Current weekly CTL gain derived from 4-week trend
    trend_4w_values = [v for _, v in trend_4w]
    if len(trend_4w_values) >= 2:
        current_4w_gain = round(
            (trend_4w_values[-1] - trend_4w_values[0]) / len(trend_4w_values), 1
        )
    else:
        current_4w_gain = 0.0

    return {
        "current_ctl": current_ctl if all_ctl else None,
        "trend_4w": trend_4w,
        "trend_4w_direction": trend_direction(trend_4w),
        "trend_12w": trend_12w,
        "trend_12w_direction": trend_direction(trend_12w),
        "yoy": {
            "2024": avg_ctl(y2024),
            "2025": avg_ctl(y2025),
            "2026": current_ctl if all_ctl else None,
        },
        # Computed planning fields
        "ctl_target": CTL_TARGET,
        "ctl_progress_pct": round((current_ctl / CTL_TARGET) * 100),
        "ctl_per_week_needed": ctl_per_week,
        "current_weekly_gain": current_4w_gain,
        "weeks_remaining_for_ctl": weeks_remaining_for_ctl,
        # Correct CTL model: solve for constant daily TSS needed to reach target in n days
        # CTL(n) = CTL₀ * exp(-n/42) + daily_tss * (1 - exp(-n/42)) = target
        # => daily_tss = (target - CTL₀ * decay) / (1 - decay)
        "weekly_tss_needed": round(
            ((CTL_TARGET - current_ctl * math.exp(-weeks_remaining_for_ctl * 7 / 42))
             / (1 - math.exp(-weeks_remaining_for_ctl * 7 / 42))) * 7
        ),
        "current_weekly_tss": round(current_4w_gain * 49),
        "projected_race_ctl": round(current_ctl + (weeks_remaining_for_ctl * current_4w_gain)),
        "projected_ctl_4w_current": round(current_ctl + (4 * current_4w_gain)),
        "projected_ctl_4w_required": round(current_ctl + (4 * ctl_per_week)),
        "projected_4w_gap": round((4 * ctl_per_week) - (4 * current_4w_gain)),
        # Current periodization phase
        "current_phase": current_phase,
        "current_phase_tss_target": current_phase["tss_target"],
        "current_phase_ctl_target": current_phase["ctl_target"],
    }

def format_ctl_report(ctl_data, total_tss_this_week=0):
    """Format a WhatsApp-friendly CTL weekly progress report."""
    current = ctl_data['current_ctl'] or 0
    target = ctl_data['ctl_target']  # 48
    pct = ctl_data['ctl_progress_pct']

    # ASCII progress bar — 20 chars wide, each char = 5%
    filled = min(int(pct / 5), 19)
    bar = "=" * filled + ">" + " " * (20 - filled - 1)
    progress_bar = f"[{bar}] {current}/{target} ({pct}%)"

    yoy = ctl_data['yoy']
    projected = ctl_data['projected_race_ctl']
    yoy_2025 = yoy.get('2025')

    phase = ctl_data.get('current_phase', {})
    phase_name = phase.get('phase', '')
    tss_lo, tss_hi = ctl_data.get('current_phase_tss_target', (0, 0))
    ctl_lo, ctl_hi = ctl_data.get('current_phase_ctl_target', (0, 0))

    if projected >= target - 2:
        projection_note = "On track"
    else:
        shortfall = target - projected
        tss_gap = max(ctl_data['weekly_tss_needed'] - ctl_data.get('current_weekly_tss', 0), 0)
        projection_note = f"Shortfall: {shortfall} pts — need ~+{tss_gap} TSS/wk"

    yoy_vs_2025 = f"{round(yoy_2025 - current, 1)} pts behind" if yoy_2025 else "N/A"

    return f"""*CTL Weekly Report*

Progress to race fitness (target: {target}):
{progress_bar}

Phase: {phase_name} | CTL target {ctl_lo}-{ctl_hi} | TSS {tss_lo}-{tss_hi}/wk
Current CTL: {current} | Race-day target: {target}
CTL gain needed: +{ctl_data['ctl_per_week_needed']}/wk | Current pace: +{ctl_data['current_weekly_gain']}/wk

*Race-day projection:*
At current pace: CTL {projected} at Tremblant
{projection_note}

*4-week projection:*
At current pace: CTL {ctl_data['projected_ctl_4w_current']} in 4 weeks
At required pace: CTL {ctl_data['projected_ctl_4w_required']} in 4 weeks
Gap: {ctl_data['projected_4w_gap']} points to close

*Year-over-year (same week):*
2024: {yoy.get('2024')} | 2025: {yoy_2025} | 2026: {current}
vs 2025: {yoy_vs_2025}"""


def get_workout_library():
    """Build a personal workout library from historical CoachChris indoor rides."""
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

    window = []
    for a in all_acts:
        dt = datetime.fromisoformat(a["start_date_local"][:10])
        is_feb_jun_2025 = dt.year == 2025 and dt.month in [2, 3, 4, 5, 6]
        if (is_feb_jun_2025
                and "CoachChris" in a.get("name", "")
                and a.get("icu_weighted_avg_watts")
                and a.get("trainer") is True
                and a.get("type") in ["VirtualRide", "Ride"]):
            window.append(a)

    def canonical_name(name):
        name = name.replace("Zwift - ", "").strip()
        if " on " in name:
            name = name[:name.rfind(" on ")]
        name = re.sub(r'\s+in\s+(Watopia|Makuri Islands|France|London|New York|Innsbruck)$', '', name).strip()
        return name

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
    for a in window:
        np_val = a["icu_weighted_avg_watts"]
        canon = canonical_name(a["name"])
        by_name[canon].append({
            "np": np_val,
            "if_val": round(np_val / 291, 2),
            "tss": a.get("icu_training_load") or 0,
            "duration_min": (a.get("moving_time") or 0) // 60
        })

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
    return library

def create_run_workout(name, workout_text, target_date=None):
    """Create a structured run workout in Intervals.icu using plain text format."""
    cfg = get_headers()

    if target_date is None:
        target_date = (date.today() + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    else:
        target_date = target_date.strftime("%Y-%m-%dT00:00:00")

    workout = {
        "name": name,
        "type": "Run",
        "category": "WORKOUT",
        "start_date_local": target_date,
        "description": workout_text
    }

    r = requests.post(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events",
        headers={**cfg["headers"], "Content-Type": "application/json"},
        json=workout
    )
    r.raise_for_status()
    result = r.json()

    steps = sum(1 for line in workout_text.split('\n') if line.strip().startswith('- '))

    return {
        "name": result.get("name", name),
        "event_id": result.get("id"),
        "steps": steps
    }


def _icu_cfg():
    """Auth config for Intervals.icu API calls."""
    import base64
    api_key = os.getenv("INTERVALS_API_KEY")
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    return {
        "base_url": "https://intervals.icu/api/v1",
        "athlete_id": athlete_id,
        "headers": {"Authorization": f"Basic {token}"},
    }


def get_most_recent_activity():
    """Return the most recent activity from today or yesterday, with id and type."""
    cfg = _icu_cfg()
    oldest = (date.today() - timedelta(days=1)).isoformat()
    newest = (date.today() + timedelta(days=1)).isoformat()
    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities",
        headers=cfg["headers"],
        params={"oldest": oldest, "newest": newest, "fields": "id,type,name,start_date_local"}
    )
    r.raise_for_status()
    acts = r.json()
    if not acts:
        return None
    act = acts[0]  # API returns newest first
    return {
        "id": act.get("id"),
        "type": act.get("type"),
        "name": act.get("name"),
        "date": act.get("start_date_local", "")[:10],
    }


def save_activity_rpe(activity_id, rpe, feel):
    """PATCH an activity with RPE (1-10) and feel (1-5)."""
    cfg = _icu_cfg()
    r = requests.patch(
        f"{cfg['base_url']}/activity/{activity_id}",
        headers={**cfg["headers"], "Content-Type": "application/json"},
        json={"icu_rpe": rpe, "feel": feel}
    )
    r.raise_for_status()
    return r.json()


def get_recent_rpe_data():
    """Return activities from the last 14 days that have RPE logged."""
    cfg = _icu_cfg()
    oldest = (date.today() - timedelta(days=14)).isoformat()
    newest = (date.today() + timedelta(days=1)).isoformat()
    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities",
        headers=cfg["headers"],
        params={
            "oldest": oldest,
            "newest": newest,
            "fields": "id,type,name,start_date_local,icu_training_load,icu_rpe,feel"
        }
    )
    r.raise_for_status()
    acts = r.json()

    feel_labels = {1: "weak", 2: "poor", 3: "normal", 4: "good", 5: "strong"}
    result = []
    for act in acts:
        if act.get("icu_rpe") is not None:
            result.append({
                "date": act.get("start_date_local", "")[:10],
                "type": act.get("type"),
                "name": act.get("name"),
                "tss": act.get("icu_training_load"),
                "rpe": act.get("icu_rpe"),
                "feel": feel_labels.get(act.get("feel")) if act.get("feel") else None,
            })
    return result


def format_weekly_summary(weekly_data, ctl_data, rpe_data):
    """Return a structured WhatsApp weekly summary string."""
    today = date.today()
    weeks_to_race = (RACE_DATE - today).days // 7

    # Phase from periodization
    current_phase = ctl_data.get('current_phase') or get_current_phase_targets()
    phase = current_phase.get('phase', 'Base')

    # Header — week of Monday
    week_start_str = weekly_data.get('week_start', today.isoformat())
    try:
        mon_date = datetime.strptime(week_start_str, '%Y-%m-%d')
        mon_str = mon_date.strftime('%b %d')
    except Exception:
        mon_str = week_start_str
    header = f"*Week of {mon_str} — {phase} | {weeks_to_race} weeks to Tremblant*"

    # FITNESS
    current_ctl = ctl_data.get('current_ctl') or 0
    target = ctl_data.get('ctl_target', CTL_RACE_TARGET)
    pct = ctl_data.get('ctl_progress_pct', round((current_ctl / target) * 100) if target else 0)
    atl = ctl_data.get('atl')
    tsb = ctl_data.get('tsb')

    # CTL week-over-week change from trend_4w (last two weekly values)
    trend_4w = ctl_data.get('trend_4w', [])
    if len(trend_4w) >= 2:
        ctl_change = round(trend_4w[-1][1] - trend_4w[-2][1], 1)
    else:
        ctl_change = 0.0
    ctl_change_str = f"+{ctl_change}" if ctl_change >= 0 else str(ctl_change)

    atl_str = f" | ATL {round(atl)}" if atl is not None else ""
    tsb_str = f" | TSB {tsb:+.0f}" if tsb is not None else ""

    filled = min(int(pct / 5), 19)
    bar = "=" * filled + ">" + " " * (20 - filled - 1)

    fitness_section = (
        f"*FITNESS*\n"
        f"CTL {round(current_ctl)} ({ctl_change_str}){atl_str}{tsb_str}\n"
        f"[{bar}] {round(current_ctl)}/{target} ({pct}%)"
    )

    # VOLUME
    def fmt_duration(mins):
        h = int(mins) // 60
        m = int(mins) % 60
        return f"{h}:{m:02d}"

    def fmt_sport(label, data, has_distance=True):
        count = data.get('count', 0)
        dur = fmt_duration(data.get('duration_min', 0))
        tss = round(data.get('tss', 0))
        return f"{label}  {count}x | {dur} | {tss} TSS"

    bike = weekly_data.get('bike', {})
    run = weekly_data.get('run', {})
    swim = weekly_data.get('swim', {})
    other = weekly_data.get('other', {})
    total_tss = weekly_data.get('total_tss', 0)
    total_count = sum(d.get('count', 0) for d in [bike, run, swim, other])
    total_dur = sum(d.get('duration_min', 0) for d in [bike, run, swim, other])

    volume_section = (
        f"*VOLUME*\n"
        f"{fmt_sport('Bike: ', bike)}\n"
        f"{fmt_sport('Run:  ', run)}\n"
        f"{fmt_sport('Swim: ', swim)}\n"
        f"{fmt_sport('Other:', other)}\n"
        f"─────────────────────────────\n"
        f"Total: {total_count}x | {fmt_duration(total_dur)} | {total_tss} TSS"
    )

    # EFFORT & FEEL — filter rpe_data to current week
    try:
        week_start_dt = datetime.strptime(week_start_str, '%Y-%m-%d').date()
    except Exception:
        week_start_dt = today - timedelta(days=today.weekday())
    week_end_dt = week_start_dt + timedelta(days=7)

    feel_words_to_int = {"weak": 1, "poor": 2, "normal": 3, "good": 4, "strong": 5}
    feel_labels_inv = {1: "weak", 2: "poor", 3: "normal", 4: "good", 5: "strong"}

    week_rpe = [
        e for e in (rpe_data or [])
        if week_start_dt.isoformat() <= e.get('date', '') < week_end_dt.isoformat()
        and e.get('rpe') is not None
    ]

    if not week_rpe:
        effort_section = "*EFFORT & FEEL*\nNo RPE data logged this week"
    else:
        avg_rpe = round(sum(e['rpe'] for e in week_rpe) / len(week_rpe), 1)

        feels = [feel_words_to_int[e['feel']] for e in week_rpe if e.get('feel') and e['feel'] in feel_words_to_int]
        if feels:
            avg_feel_word = feel_labels_inv.get(round(sum(feels) / len(feels)), 'normal')
        else:
            avg_feel_word = 'N/A'

        hardest = max(week_rpe, key=lambda e: e['rpe'])
        easiest = min(week_rpe, key=lambda e: e['rpe'])

        def activity_label(e):
            return e.get('name') or e.get('type', 'Activity')

        effort_section = (
            f"*EFFORT & FEEL*\n"
            f"Avg RPE: {avg_rpe}/10 | Avg Feel: {avg_feel_word}\n"
            f"Hardest: {activity_label(hardest)} — RPE {hardest['rpe']}, {hardest.get('feel') or 'N/A'}\n"
            f"Easiest: {activity_label(easiest)} — RPE {easiest['rpe']}, {easiest.get('feel') or 'N/A'}"
        )

    # PROJECTION
    projected_race_ctl = ctl_data.get('projected_race_ctl', 0)
    ctl_gap = round(target - current_ctl, 1)
    ctl_per_week = ctl_data.get('ctl_per_week_needed', 0)
    current_gain = ctl_data.get('current_weekly_gain', 0)

    # Phase targets for TSS comparison
    tss_lo, tss_hi = ctl_data.get('current_phase_tss_target', (0, 0))
    ctl_lo, ctl_hi = ctl_data.get('current_phase_ctl_target', (0, 0))

    # Next phase
    today_iso = today.isoformat()
    next_phase = None
    for i, p in enumerate(PERIODIZATION):
        if p["start"] <= today_iso <= p["end"] and i + 1 < len(PERIODIZATION):
            next_phase = PERIODIZATION[i + 1]
            break

    def fmt_phase_date(d_str):
        try:
            return datetime.strptime(d_str, '%Y-%m-%d').strftime('%b %d')
        except Exception:
            return d_str

    phase_range = f"{fmt_phase_date(current_phase['start'])} - {fmt_phase_date(current_phase['end'])}"
    phase_line = f"Phase: {phase} ({phase_range}) → CTL {ctl_lo}-{ctl_hi}, TSS {tss_lo}-{tss_hi}/wk"

    if next_phase:
        next_line = f"Next:  {next_phase['phase']} starts {fmt_phase_date(next_phase['start'])}"
    else:
        next_line = "Next:  Race week"

    # Shortfall indicator for race projection
    race_gap = target - projected_race_ctl
    if race_gap <= 1:
        race_indicator = "on target"
    else:
        race_indicator = f"{race_gap} pts short"

    # TSS vs phase target (compare to low end)
    tss_vs_phase = total_tss - tss_lo
    tss_vs_str = f"+{tss_vs_phase}" if tss_vs_phase >= 0 else str(tss_vs_phase)

    projection_section = (
        f"*PROJECTION*\n"
        f"{phase_line}\n"
        f"{next_line}\n\n"
        f"Race-day target: CTL {target} | Current: {round(current_ctl)} | Gap: {ctl_gap} pts\n"
        f"At current pace (+{current_gain}/wk) → CTL {projected_race_ctl} race week ({race_indicator})\n"
        f"At required pace (+{ctl_per_week}/wk) → CTL {target} race week (on target)\n"
        f"This week: {total_tss} TSS (target {tss_lo}-{tss_hi}, {tss_vs_str} vs target)"
    )

    # YEAR OVER YEAR
    yoy = ctl_data.get('yoy', {})
    ctl_2026 = yoy.get('2026') or round(current_ctl)
    ctl_2025 = yoy.get('2025')
    ctl_2024 = yoy.get('2024')

    if ctl_2025 is not None:
        yoy_diff = round(ctl_2025 - current_ctl, 1)
        direction = "behind" if yoy_diff > 0 else "ahead"
        yoy_vs = f"vs 2025: {abs(yoy_diff)} pts {direction}"
    else:
        yoy_vs = "vs 2025: N/A"

    yoy_section = (
        f"*YEAR OVER YEAR*\n"
        f"2026: {ctl_2026} | 2025: {ctl_2025 or 'N/A'} | 2024: {ctl_2024 or 'N/A'}\n"
        f"{yoy_vs}"
    )

    return "\n\n".join([header, fitness_section, volume_section, effort_section, projection_section, yoy_section])