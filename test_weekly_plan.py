from dotenv import load_dotenv
load_dotenv()

from garmin_client import get_readiness_data
from intervals_client import get_fitness_data, get_ctl_trajectory, get_weekly_summary
from coach import summarize_garmin, summarize_intervals, get_weekly_plan

garmin_data = get_readiness_data()
intervals_data = get_fitness_data()
garmin_summary = summarize_garmin(garmin_data)
intervals_summary = summarize_intervals(intervals_data)
ctl_data = get_ctl_trajectory()
weekly = get_weekly_summary()

plan = get_weekly_plan(garmin_summary, intervals_summary, ctl_data, weekly)
print(plan)
