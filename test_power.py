from dotenv import load_dotenv
load_dotenv()

from intervals_client import get_fitness_data, get_headers
import requests
import json

data = get_fitness_data()
ride = next(a for a in data['recent_activities'] if a.get('type') == 'VirtualRide')
cfg = get_headers()
act_id = ride.get('id')

r = requests.get(f"{cfg['base_url']}/activity/{act_id}", headers=cfg['headers'])
full = r.json()

print("Power fields:")
print(f"  icu_average_watts: {full.get('icu_average_watts')}")
print(f"  icu_weighted_avg_watts: {full.get('icu_weighted_avg_watts')}")
print(f"  icu_intensity (IF x100): {full.get('icu_intensity')}")
print(f"  icu_training_load (TSS): {full.get('icu_training_load')}")
print(f"  icu_ftp: {full.get('icu_ftp')}")

print("\nEnriched activity from get_fitness_data:")
print(json.dumps(ride, indent=2))