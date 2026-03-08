from dotenv import load_dotenv
load_dotenv()

from garmin_client import get_readiness_data
from intervals_client import get_fitness_data
from coach import get_recommendation

print("=== Triathlon Coach ===\n")

print("Fetching Garmin readiness data...")
garmin_data = get_readiness_data()

print("Fetching Intervals.icu fitness data...")
intervals_data = get_fitness_data()

print("Generating recommendation...\n")
recommendation = get_recommendation(garmin_data, intervals_data)

print("=" * 50)
print(recommendation)
print("=" * 50)