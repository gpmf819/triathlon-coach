import json
from dotenv import load_dotenv
load_dotenv()

from garmin_client import get_readiness_data

print("=== Testing Garmin data fetch ===\n")
data = get_readiness_data()
print("\n=== Raw data ===")
print(json.dumps(data, indent=2, default=str))