from dotenv import load_dotenv
load_dotenv()
from intervals_client import get_weekly_summary
import json

print(json.dumps(get_weekly_summary(), indent=2))