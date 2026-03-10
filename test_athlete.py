from dotenv import load_dotenv
load_dotenv()

from intervals_client import get_athlete_profile
import json

profile = get_athlete_profile()
print(json.dumps(profile, indent=2))