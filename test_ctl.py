from dotenv import load_dotenv
load_dotenv()
from intervals_client import get_ctl_trajectory
import json

data = get_ctl_trajectory()

print(f"Current CTL: {data['current_ctl']}")
print(f"\n4-week trend ({data['trend_4w_direction']}):")
for week, ctl in data['trend_4w']:
    print(f"  {week}: {ctl}")

print(f"\n12-week trend ({data['trend_12w_direction']}):")
for week, ctl in data['trend_12w']:
    print(f"  {week}: {ctl}")

print(f"\nYear-over-year (same week of March):")
for year, ctl in data['yoy'].items():
    print(f"  {year}: CTL {ctl}")