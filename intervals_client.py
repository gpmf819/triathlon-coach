import requests
import os
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

def get_headers():
    api_key = os.getenv("INTERVALS_API_KEY")
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    return {
        "headers": {"Authorization": f"Basic {__import__('base64').b64encode(f'API_KEY:{api_key}'.encode()).decode()}"},
        "athlete_id": athlete_id,
        "base_url": "https://intervals.icu/api/v1"
    }

def get_fitness_data():
    cfg = get_headers()
    today = date.today().isoformat()
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
            "fields": "type,name,start_date_local,moving_time,distance,average_heartrate,max_heartrate,average_watts,normalized_power,intensity_factor,tss,average_speed,suffer_score"
        }
    )
    activities.raise_for_status()

    return {
        "wellness": wellness.json(),
        "recent_activities": activities.json()
    }

def get_athlete_profile():
    cfg = get_headers()
    url = f"{cfg['base_url']}/athlete/{cfg['athlete_id']}"
    response = requests.get(url, headers=cfg["headers"])
    response.raise_for_status()
    return response.json()

def summarize_athlete_profile(profile):
    """Extract key coaching metrics from athlete profile."""
    bike_settings = next((s for s in profile.get("sportSettings", []) 
                         if "Ride" in s.get("types", [])), {})
    run_settings = next((s for s in profile.get("sportSettings", []) 
                        if "Run" in s.get("types", [])), {})
    swim_settings = next((s for s in profile.get("sportSettings", []) 
                         if "Swim" in s.get("types", [])), {})

    return {
        "weight_kg": profile.get("icu_weight"),
        "resting_hr": profile.get("icu_resting_hr"),
        "dob": profile.get("icu_date_of_birth"),
        "bike": {
            "ftp": 291,  # confirmed via ramp test, overrides Intervals value of 270
            "lthr": bike_settings.get("lthr"),
            "max_hr": bike_settings.get("max_hr"),
            "power_zones": bike_settings.get("power_zones"),
            "power_zone_names": bike_settings.get("power_zone_names"),
            "hr_zones": bike_settings.get("hr_zones"),
        },
        "run": {
            "lthr": run_settings.get("lthr"),
            "max_hr": run_settings.get("max_hr"),
            "hr_zones": run_settings.get("hr_zones"),
            "threshold_pace": run_settings.get("threshold_pace"),
        },
        "swim": {
            "threshold_pace_per_100m": "1:55/100m",
            "max_hr": swim_settings.get("max_hr"),
        }
    }