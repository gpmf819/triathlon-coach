from dotenv import load_dotenv
load_dotenv()

from intervals_client import get_headers
import requests

cfg = get_headers()

r = requests.delete(
    f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events/99207785",
    headers=cfg["headers"]
)
print(f"Delete test workout: {r.status_code}")