from dotenv import load_dotenv
load_dotenv()
from intervals_client import get_workout_library

lib = get_workout_library()
print(f"Library loaded: {len(lib)} workouts")
for w in lib:
    print(f"  {w['zone']} | IF {w['median_if']} | {w['name']}")