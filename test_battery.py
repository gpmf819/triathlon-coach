import garth
import os
from datetime import date, timedelta
from dotenv import load_dotenv
import json

load_dotenv()

garth.resume(os.path.expanduser("~/.garth"))
client = garth.client
username = client.username

target = (date.today() - timedelta(days=1)).isoformat()
print(f"Testing battery endpoints for {target}\n")

# Test 1
try:
    r = client.connectapi(f"/wellness-service/wellness/dailySummaryChart/{username}", params={"date": target})
    print("Test 1 - dailySummaryChart:")
    print(json.dumps(r, indent=2, default=str)[:500])
except Exception as e:
    print(f"Test 1 failed: {e}")

# Test 2
try:
    r = client.connectapi(f"/wellness-service/wellness/daily/{username}", params={"date": target})
    print("\nTest 2 - daily wellness:")
    print(json.dumps(r, indent=2, default=str)[:500])
except Exception as e:
    print(f"Test 2 failed: {e}")