import json
from dotenv import load_dotenv
load_dotenv()

from intervals_client import get_fitness_data

print("=== Testing Intervals.icu data fetch ===\n")
data = get_fitness_data()

# Print wellness summary
print("--- Wellness (last 7 days) ---")
for day in data["wellness"]:
    print(f"{day.get('id')}: CTL={day.get('ctl')}, ATL={day.get('atl')}, TSB={day.get('tsb')}")

# Print recent activities
print("\n--- Recent Activities ---")
for act in data["recent_activities"][:5]:
    print(f"{act.get('start_date_local','')[:10]} | {act.get('type','?')} | {act.get('name','?')} | {act.get('moving_time',0)//60}min")