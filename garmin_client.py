import garth
import os
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

def authenticate():
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    token_dir = os.path.expanduser("~/.garth")

    try:
        garth.resume(token_dir)
        garth.client.username
        print("Resumed existing Garmin session")
    except Exception:
        print("Logging in to Garmin...")
        garth.login(email, password)
        garth.save(token_dir)
        print("Login successful, tokens saved")

    return garth.client

def get_readiness_data(days_back=1):
    client = authenticate()
    target = date.today() - timedelta(days=days_back)
    date_str = target.isoformat()
    username = client.username
    print(f"Fetching readiness data for {date_str} (user: {username})")

    results = {"date": date_str}

    # Body battery - not reliably available via API for Forerunner 945
    results["body_battery"] = None

    # Sleep
    try:
        sleep = client.connectapi(
            f"/wellness-service/wellness/dailySleepData/{username}",
            params={"date": date_str}
        )
        results["sleep"] = sleep
        print("✓ Sleep data fetched")
    except Exception as e:
        print(f"✗ Sleep failed: {e}")
        results["sleep"] = None

    # HRV
    try:
        hrv = client.connectapi(f"/hrv-service/hrv/{date_str}")
        results["hrv"] = hrv
        print("✓ HRV fetched")
    except Exception as e:
        print(f"✗ HRV failed: {e}")
        results["hrv"] = None

    return results