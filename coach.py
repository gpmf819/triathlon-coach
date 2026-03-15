import anthropic
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

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
        entry = {
            "date": act.get("start_date_local", "")[:10],
            "type": act.get("type"),
            "name": act.get("name"),
            "duration_min": (act.get("moving_time", 0) or 0) // 60,
            "distance_km": round((act.get("distance", 0) or 0) / 1000, 1),
        }

        # HR data
        if act.get("average_heartrate"):
            entry["avg_hr"] = round(act["average_heartrate"])
        if act.get("max_heartrate"):
            entry["max_hr"] = round(act["max_heartrate"])

        # Bike power data
        if act.get("average_watts"):
            entry["avg_power"] = round(act["average_watts"])
        if act.get("normalized_power"):
            entry["normalized_power"] = round(act["normalized_power"])
        if act.get("intensity_factor"):
            entry["intensity_factor"] = round(act["intensity_factor"], 2)

        # TSS
        if act.get("tss"):
            entry["tss"] = round(act["tss"])

        # Run pace (convert m/s to min/km)
        if act.get("average_speed") and act.get("type") in ["Run", "VirtualRun", "TrailRun"]:
            speed_ms = act["average_speed"]
            if speed_ms > 0:
                pace_sec_per_km = 1000 / speed_ms
                mins = int(pace_sec_per_km // 60)
                secs = int(pace_sec_per_km % 60)
                entry["avg_pace"] = f"{mins}:{secs:02d}/km"

        recent.append(entry)

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

    from intervals_client import get_athlete_profile, summarize_athlete_profile, get_workout_library, get_ctl_trajectory, get_weekly_summary
    raw_profile = get_athlete_profile()
    athlete_metrics = summarize_athlete_profile(raw_profile)
    intervals_summary = summarize_intervals(intervals_data)

    today_str = datetime.now().strftime("%A, %B %d, %Y")
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%A, %B %d, %Y")

    # Build workout library text
    workout_library = get_workout_library()
    workout_library_text = "\n".join([
        f"- {w['zone']} | IF {w['median_if']} | NP {w['median_np']}W | TSS {w['median_tss']} | {w['median_duration_min']}min | {w['name']}"
        for w in workout_library
    ])

    ctl_data = get_ctl_trajectory()
    trend_4w_str = " → ".join([str(v) for _, v in ctl_data['trend_4w']])
    trend_12w_str = " → ".join([str(v) for _, v in ctl_data['trend_12w']])
    yoy = ctl_data['yoy']
    weekly = get_weekly_summary()

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

Today is {today_str}. Tomorrow is {tomorrow_str}. Your workout recommendation is for tomorrow.

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

## CTL Trajectory
- 4-week trend: {trend_4w_str} ({ctl_data['trend_4w_direction']})
- 12-week trend: {trend_12w_str} ({ctl_data['trend_12w_direction']})
- Target: CTL 55-60 by race week (June 13). Currently {ctl_data['current_ctl']} — need +{round(55 - ctl_data['current_ctl'], 1)} points in 13 weeks (~+{round((55 - ctl_data['current_ctl']) / 13, 1)}/week)

## This Week's Training Summary (since {weekly['week_start']})
- Bike: {weekly['bike']['count']} sessions | {weekly['bike']['duration_min']}min | TSS {weekly['bike']['tss']}
- Run: {weekly['run']['count']} sessions | {weekly['run']['duration_min']}min | TSS {weekly['run']['tss']}
- Swim: {weekly['swim']['count']} sessions | {weekly['swim']['duration_min']}min | TSS {weekly['swim']['tss']}
- Other: {weekly['other']['count']} sessions | {weekly['other']['duration_min']}min | TSS {weekly['other']['tss']}
- Total week TSS: {weekly['total_tss']} | Days done: {weekly['days_done']}/7

## Year-over-Year CTL (same week of March)
- 2024: {yoy['2024']} | 2025: {yoy['2025']} | 2026: {yoy['2026']} (current)
- Context: 2026 is {round(yoy['2025'] - yoy['2026'], 1) if yoy['2025'] and yoy['2026'] else 'N/A'} points behind 2025 pace, {round(yoy['2026'] - yoy['2024'], 1) if yoy['2024'] and yoy['2026'] else 'N/A'} points ahead of 2024 pace

## Recent Activities (last 7 days)
{intervals_summary['recent_activities']}

## Periodization Context
- 15 weeks to race. Currently in base building phase.
- Priority order: Bike > Run > Swim (swim resumes April)
- Week structure goal: 3 bikes, 3 runs, 1 rest day (adjust based on readiness)
- CTL target progression: aim to reach CTL ~55-60 by race week taper
- Key limiters to address: bike power (FTP improvement), run off-bike (brick fitness), swim efficiency

## Zwift Workout Library (personal verified workouts — ONLY recommend from this list for bike sessions)
{workout_library_text}

CRITICAL RULES for bike workout recommendations:
1. You MUST select a workout from the library above — never invent or guess workout names
2. Match the workout zone (Z2 Endurance / Tempo / Sweet Spot / Threshold) to the prescribed training intensity
3. Consider the TSS and duration relative to the athlete's current fatigue (ATL) and form (TSB)
4. State the exact workout name as it appears in the library

## Your Task
Recommend tomorrow's training session. Be specific and practical.

Respond in this exact format:

**RECOMMENDATION**: [Rest / Easy / Moderate / Hard]
**SPORT**: [Bike / Run / Swim / Rest / Cross-train]
**DURATION**: [e.g. 60 min]
**WORKOUT**:
[Structured workout with warm-up, main set, cool-down. Include zones, power targets if bike, pace targets if run.]

**ZWIFT WORKOUT** (only if sport is Bike):
[Exact workout name from the library above]
Zone: [zone classification]
Expected NP: ~[NP]W | IF: [IF] | TSS: ~[TSS]

**RATIONALE**: 2-3 sentences explaining why this session given today's readiness and training load.

**WEEKLY CONTEXT**: One sentence on where this fits in the week's overall load.
"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text