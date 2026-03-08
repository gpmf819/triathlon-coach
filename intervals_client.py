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

    # Wellness (CTL/ATL/TSB/form)
    wellness_url = f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/wellness"
    wellness = requests.get(
        wellness_url,
        headers=cfg["headers"],
        params={"oldest": week_ago, "newest": today}
    )
    wellness.raise_for_status()

    # Recent activities
    activities_url = f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities"
    activities = requests.get(
        activities_url,
        headers=cfg["headers"],
        params={"oldest": week_ago, "newest": today}
    )
    activities.raise_for_status()

    return {
        "wellness": wellness.json(),
        "recent_activities": activities.json()
    }