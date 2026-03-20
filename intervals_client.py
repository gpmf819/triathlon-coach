import requests
import os
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


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

    return {
        "current_ctl": all_ctl[-1]["ctl"] if all_ctl else None,
        "trend_4w": trend_4w,
        "trend_4w_direction": trend_direction(trend_4w),
        "trend_12w": trend_12w,
        "trend_12w_direction": trend_direction(trend_12w),
        "yoy": {
            "2024": avg_ctl(y2024),
            "2025": avg_ctl(y2025),
            "2026": all_ctl[-1]["ctl"] if all_ctl else None
        }
    }

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
    """Auth config for new ICU_API_KEY-based calls."""
    import base64
    api_key = os.getenv("ICU_API_KEY")
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
            "fields": "id,type,start_date_local,icu_training_load,icu_rpe,feel"
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
                "tss": act.get("icu_training_load"),
                "rpe": act.get("icu_rpe"),
                "feel": feel_labels.get(act.get("feel")) if act.get("feel") else None,
            })
    return result