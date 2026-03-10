import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

def summarize_garmin(garmin_data):
    """Extract the key numbers from raw Garmin data."""
    summary = {"date": garmin_data.get("date")}

    # Body battery
    bb = garmin_data.get("body_battery")
    if bb and isinstance(bb, list) and len(bb) > 0:
        summary["body_battery_end"] = bb[-1].get("value")
        summary["body_battery_start"] = bb[0].get("value")
        summary["body_battery_change"] = bb[-1].get("value") - bb[0].get("value")
    elif isinstance(bb, dict):
        readings = bb.get("bodyBatteryValuesArray", [])
        if readings:
            summary["body_battery_end"] = readings[-1][1] if readings else None

    # Sleep
    sleep = garmin_data.get("sleep")
    if sleep and isinstance(sleep, dict):
        daily = sleep.get("dailySleepDTO", {})
        summary["sleep_duration_hours"] = round(daily.get("sleepTimeSeconds", 0) / 3600, 1)
        summary["sleep_score"] = daily.get("sleepScores", {}).get("overall", {}).get("value")
        summary["deep_sleep_hours"] = round(daily.get("deepSleepSeconds", 0) / 3600, 1)
        summary["rem_sleep_hours"] = round(daily.get("remSleepSeconds", 0) / 3600, 1)

    # HRV
    hrv = garmin_data.get("hrv")
    if hrv and isinstance(hrv, dict):
        summary["hrv_weekly_avg"] = hrv.get("hrvSummary", {}).get("weeklyAvg")
        summary["hrv_last_night"] = hrv.get("hrvSummary", {}).get("lastNight")
        summary["hrv_status"] = hrv.get("hrvSummary", {}).get("status")

    return summary

def summarize_intervals(intervals_data):
    """Extract the key fitness metrics from Intervals.icu data."""
    wellness = intervals_data.get("wellness", [])
    activities = intervals_data.get("recent_activities", [])

    today_wellness = wellness[-1] if wellness else {}
    ctl = today_wellness.get("ctl", 0) or 0
    atl = today_wellness.get("atl", 0) or 0
    tsb = ctl - atl

    recent = []
    for act in activities[:7]:
        recent.append({
            "date": act.get("start_date_local", "")[:10],
            "type": act.get("type"),
            "name": act.get("name"),
            "duration_min": (act.get("moving_time", 0) or 0) // 60,
            "distance_km": round((act.get("distance", 0) or 0) / 1000, 1),
        })

    return {
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(tsb, 1),
        "recent_activities": recent
    }

def get_recommendation(garmin_data, intervals_data, athlete_profile=None):
    """Call Claude to generate tomorrow's training recommendation."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    garmin_summary = summarize_garmin(garmin_data)
    from intervals_client import get_athlete_profile, summarize_athlete_profile
    raw_profile = get_athlete_profile()
    athlete_metrics = summarize_athlete_profile(raw_profile)
    intervals_summary = summarize_intervals(intervals_data)

    if athlete_profile is None:
        athlete_profile = {
            "name": "Gaël",
            "age_group": "40-44",
            "target_race": "Tremblant 5150 (Olympic distance)",
            "race_date": "June 20, 2026",
            "weeks_to_race": 15,
            "previous_best": {
                "total": "2:44:39",
                "swim": "0:28:39 (1.5km)",
                "bike": "1:16:33 (40km)",
                "run": "0:51:00 (10km)",
                "placement": "9th age group"
            },
            "goal": "Top 5 age group finish. Key gains on bike and run. Swim maintained but not primary focus until April.",
            "current_phase": "Base building (winter). Bike and run are priority sports. Swimming resumes April 2026.",
            "available_equipment": ["Zwift (indoor bike)", "outdoor run", "treadmill", "alpine skiing (cross-training)"],
            "notes": "Montreal-based. Currently in mixed winter block. No training constraints. CTL is low (24) — this is a base building phase, progressively building volume through spring before race-specific work in May/June."
        }

    prompt = f"""You are an expert triathlon coach preparing an athlete for a specific A-race. Based on the athlete's readiness data and recent training load, recommend tomorrow's training session.

## Athlete Profile
- Name: {athlete_profile['name']}, Age: 44, Male, 75kg
- Target race: {athlete_profile['target_race']} on {athlete_profile['race_date']} ({athlete_profile['weeks_to_race']} weeks away)
- Previous best: Total 2:44:39 | Swim 0:28:39 | Bike 1:16:33 | Run 0:51:00 (9th AG)
- Goal: Top 5 age group finish

## Athlete Physiology
- Resting HR: {athlete_metrics['resting_hr']} bpm | Max HR: {athlete_metrics['bike']['max_hr']} bpm
- Bike FTP: {athlete_metrics['bike']['ftp']}W (confirmed ramp test)
- Bike LTHR: {athlete_metrics['bike']['lthr']} bpm
- Bike power zones: {dict(zip(athlete_metrics['bike']['power_zone_names'], athlete_metrics['bike']['power_zones']))}
- Run LTHR: {athlete_metrics['run']['lthr']} bpm
- Run HR zones: {athlete_metrics['run']['hr_zones']}
- Swim threshold pace: {athlete_metrics['swim']['threshold_pace_per_100m']}

## Today's Readiness (from Garmin)
- Sleep duration: {garmin_summary.get('sleep_duration_hours')} hours
- Sleep score: {garmin_summary.get('sleep_score')}
- Deep sleep: {garmin_summary.get('deep_sleep_hours')} hours
- REM sleep: {garmin_summary.get('rem_sleep_hours')} hours
- Body battery start of day: {garmin_summary.get('body_battery_start')}
- Body battery end of day: {garmin_summary.get('body_battery_end')}
- HRV last night: {garmin_summary.get('hrv_last_night')}
- HRV weekly avg: {garmin_summary.get('hrv_weekly_avg')}
- HRV status: {garmin_summary.get('hrv_status')}

## Training Load (from Intervals.icu)
- Fitness (CTL): {intervals_summary['ctl']} — chronic training load
- Fatigue (ATL): {intervals_summary['atl']} — acute training load
- Form (TSB): {intervals_summary['tsb']} — fitness minus fatigue
- TSB guide: above +10 = very fresh, 0 to -10 = optimal training zone, -10 to -30 = heavy load, below -30 = overreaching

## Recent Activities (last 7 days)
{intervals_summary['recent_activities']}

## Periodization Context
- 15 weeks to race. Currently in base building phase.
- Priority order: Bike > Run > Swim (swim resumes April)
- Week structure goal: 3 bikes, 3 runs, 1 rest day (adjust based on readiness)
- CTL target progression: aim to reach CTL ~55-60 by race week taper
- Key limiters to address: bike power (FTP improvement), run off-bike (brick fitness), swim efficiency

## Zwift Workout Library Reference
When recommending a Zwift bike session, suggest a specific named workout from Zwift's built-in library. Here are the main categories and example workouts by training type:

EASY/RECOVERY (Zone 1-2):
- "Endurance" category: "Active Recovery", "Coffee Ride", "Relaxed Ride"
- "FTP Builders" category: "Endurance Ride I", "Endurance Ride II"

TEMPO/SWEET SPOT (Zone 3-4):
- "Sweet Spot" category: "Ramp Up I", "Ramp Up II", "Ramp Up III"
- "FTP Builders": "Threshold Buster I", "Threshold Buster II"
- "Triathlon" category: "Olympic Distance Base I", "Olympic Distance Base II"

VO2MAX/HARD (Zone 5):
- "FTP Builders": "FTP Booster I", "FTP Booster II"
- "Climbing" category: "Peak Power I", "Peak Power II"
- "Triathlon": "Olympic Distance Build I", "Olympic Distance Build II"

BASE BUILDING:
- "Triathlon" category: "70.3 Base I", "70.3 Base II", "Olympic Distance Base I"
- "Gran Fondo": "Gran Fondo Prep I", "Gran Fondo Prep II"

## Your Task
Recommend tomorrow's training session. Be specific and practical.

Respond in this exact format:

**RECOMMENDATION**: [Rest / Easy / Moderate / Hard]
**SPORT**: [Bike / Run / Swim / Rest / Cross-train]
**DURATION**: [e.g. 60 min]
**WORKOUT**:
[Structured workout with warm-up, main set, cool-down. Include zones, power targets if bike, pace targets if run.]

**ZWIFT WORKOUT** (only if sport is Bike):
- Category: [exact Zwift category name]
- Workout: [exact Zwift workout name]
- Where to find it: Zwift menu → Workouts → [Category] → [Workout name]

**RATIONALE**: 2-3 sentences explaining why this session given today's readiness and training load.

**WEEKLY CONTEXT**: One sentence on where this fits in the week's overall load.
"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text