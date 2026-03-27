import anthropic
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, date
from utils import get_system_time_block

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


def get_training_phase(weeks_to_race=None):
    """Return current training phase name and description based on periodization timeline."""
    from intervals_client import get_current_phase_targets, PHASE_DESCRIPTIONS
    phase = get_current_phase_targets()
    phase_name = phase["phase"]
    tss_lo, tss_hi = phase["tss_target"]
    base_desc = PHASE_DESCRIPTIONS.get(phase_name, "")
    description = f"{base_desc} Target {tss_lo}-{tss_hi} TSS/wk."
    return phase_name, description


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

    from intervals_client import get_athlete_profile, summarize_athlete_profile, get_workout_library, get_ctl_trajectory, get_weekly_summary, get_current_phase_targets, PERIODIZATION, CTL_RACE_TARGET
    raw_profile = get_athlete_profile()
    athlete_metrics = summarize_athlete_profile(raw_profile)
    intervals_summary = summarize_intervals(intervals_data)

    # Dynamic race countdown
    race_date = date(2026, 6, 20)
    weeks_to_race = (race_date - date.today()).days // 7
    days_to_race = (race_date - date.today()).days
    weeks_remaining_for_ctl = max(weeks_to_race - 2, 1)

    # Dynamic training phase
    phase_name, phase_description = get_training_phase(weeks_to_race)

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

    ctl_gap = round(CTL_RACE_TARGET - ctl_data['current_ctl'], 1)
    ctl_per_week = round(ctl_gap / weeks_remaining_for_ctl, 1)
    current_phase = get_current_phase_targets()
    tss_lo, tss_hi = current_phase["tss_target"]
    ctl_lo, ctl_hi = current_phase["ctl_target"]

    weekly = get_weekly_summary()

    if athlete_profile is None:
        athlete_profile = {
            "name": "Gaël",
            "age_group": "40-44",
            "target_race": "Tremblant 5150 (Olympic distance)",
            "race_date": "June 20, 2026",
            "weeks_to_race": weeks_to_race,
            "previous_best": {
                "total": "2:44:39",
                "swim": "0:28:39 (1.5km)",
                "bike": "1:16:33 (40km)",
                "run": "0:51:00 (10km)",
                "placement": "9th age group"
            },
            "goal": "Top 5 age group finish. Key gains on bike and run.",
        }

    prompt = f"""{get_system_time_block()}

You are an expert triathlon coach preparing an athlete for a specific A-race. Based on the athlete's readiness data and recent training load, recommend today's training session.

Your workout recommendation is for workout_recommendation_is_for as specified in [SYSTEM_TIME] above.

## Athlete Profile
- Name: {athlete_profile['name']}, Age: 44, Male, 75kg
- Target race: {athlete_profile['target_race']} on {athlete_profile['race_date']} ({weeks_to_race} weeks / {days_to_race} days away)
- Previous best: Total 2:44:39 | Swim 0:28:39 | Bike 1:16:33 | Run 0:51:00 (9th AG)
- Goal: Top 5 age group finish

## Athlete Physiology
- Resting HR: {athlete_metrics['resting_hr']} bpm | Max HR: {athlete_metrics['bike']['max_hr']} bpm
- Bike FTP: {athlete_metrics['bike']['ftp']}W (confirmed ramp test)
- Bike LTHR: {athlete_metrics['bike']['lthr']} bpm
- Bike power zones: {dict(zip(athlete_metrics['bike']['power_zone_names'], athlete_metrics['bike']['power_zones']))}
- Run LTHR: {athlete_metrics['run']['lthr']} bpm
- Run HR zones (confirmatory only): {athlete_metrics['run']['hr_zones']}
- Swim threshold pace: {athlete_metrics['swim']['threshold_pace_per_100m']}

## Run Prescription Philosophy
Runs are prescribed using pace as the PRIMARY metric, RPE as SECONDARY, and HR as CONFIRMATORY only.
- HR is a lagging indicator — it takes 60-90 seconds to respond to pace changes
- Never prescribe HR as a target to chase in real time — athletes should control effort via pace and feel
- HR zones are provided as a confirmation check only: if HR is consistently above the expected range after 2 minutes of settling, the pace is too fast

## Athlete Run Paces (derived from recent activity data)
- Easy / Z2 pace: 5:50-6:10/km | RPE 3/10 | fully conversational | HR settles 145-153 after warmup
- Tempo / Z3 pace: 5:05-5:20/km | RPE 6-7/10 | short phrases only | HR settles 154-162 after 90s
- Threshold / Z4 pace: 4:45-5:00/km | RPE 8/10 | cannot speak | HR settles 163-171 after 90s
- Note: HR will lag pace by 60-90 seconds at start of each interval — this is normal, do not slow down

## Today's Readiness (from Garmin)
- Sleep duration: {garmin_summary.get('sleep_duration_hours')} hours
- Sleep score: {garmin_summary.get('sleep_score')}
- Deep sleep: {garmin_summary.get('deep_sleep_hours')} hours
- REM sleep: {garmin_summary.get('rem_sleep_hours')} hours
- Body battery start: {garmin_summary.get('body_battery_start')}
- Body battery end: {garmin_summary.get('body_battery_end')}
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
- Race-day target: CTL {CTL_RACE_TARGET} (Olympic distance). Currently {ctl_data['current_ctl']} — need +{ctl_gap} pts in {weeks_remaining_for_ctl} weeks (~+{ctl_per_week}/wk)

## Year-over-Year CTL (same week)
- 2024: {yoy['2024']} | 2025: {yoy['2025']} | 2026: {yoy['2026']} (current)
- Context: 2026 is {round(yoy['2025'] - yoy['2026'], 1) if yoy['2025'] and yoy['2026'] else 'N/A'} points behind 2025 pace, {round(yoy['2026'] - yoy['2024'], 1) if yoy['2024'] and yoy['2026'] else 'N/A'} points ahead of 2024 pace

## This Week's Training Summary (since {weekly['week_start']})
- Bike: {weekly['bike']['count']} sessions | {weekly['bike']['duration_min']}min | TSS {weekly['bike']['tss']}
- Run: {weekly['run']['count']} sessions | {weekly['run']['duration_min']}min | TSS {weekly['run']['tss']}
- Swim: {weekly['swim']['count']} sessions | {weekly['swim']['duration_min']}min | TSS {weekly['swim']['tss']}
- Other: {weekly['other']['count']} sessions | {weekly['other']['duration_min']}min | TSS {weekly['other']['tss']}
- Total week TSS: {weekly['total_tss']} | Days done: {weekly['days_done']}/7

## Recent Activities (last 7 days)
{intervals_summary['recent_activities']}

## Periodization Context
- {weeks_to_race} weeks ({days_to_race} days) to race
- Current phase: {phase_name} — {phase_description}
- Current phase targets: CTL {ctl_lo}-{ctl_hi} | TSS {tss_lo}-{tss_hi}/wk
- Race-day CTL target: {CTL_RACE_TARGET} (Olympic distance / 5150)
- Week structure goal: 3 bikes, 3 runs, 1 rest day (adjust based on readiness)
- Key limiters: bike power (FTP improvement), run off-bike (brick fitness), swim efficiency

## Full Periodization Timeline
Base 1 (Mar 21-27): CTL 25-30, TSS 260-290/wk — consistency focus
Base 2 (Mar 28-Apr 10): CTL 30-35, TSS 290-320/wk — aerobic volume
Late Base (Apr 11-24): CTL 35-40, TSS 320-350/wk — swim integrated
Build 1 (Apr 25-May 8): CTL 40-45, TSS 350-380/wk — threshold + bricks
Build 2 (May 9-22): CTL 45-50, TSS 380-420/wk — race-pace intervals
Peak (May 23-Jun 5): CTL 50-52, TSS 400-450/wk — Olympic distance simulation
Taper 1 (Jun 6-12): CTL 50-52, TSS 200-250/wk — sharpen + freshen
Race Week (Jun 13-20): CTL 48-50, TSS 100-150/wk — activation only

## Zwift Workout Library (personal verified workouts — ONLY recommend from this list for bike sessions)
{workout_library_text}

CRITICAL RULES for bike workout recommendations:
1. You MUST select a workout from the library above — never invent or guess workout names
2. Match the workout zone (Z2 Endurance / Tempo / Sweet Spot / Threshold) to the prescribed training intensity
3. Consider the TSS and duration relative to the athlete's current fatigue (ATL) and form (TSB)
4. State the exact workout name as it appears in the library

## Run Workout Format Rules
- Step names must be descriptive and concise — they display on the Garmin watch
- Include RPE in step name: "Warmup easy RPE3", "Tempo RPE6-7", "Recovery RPE3"
- Include HR confirmation in interval step names: "Tempo RPE6-7 HR154-162"
- Pace targets go in the step duration line: "- 10m 5:05-5:20/km"
- Always include warmup and cooldown steps
- For interval runs, alternate work and recovery steps explicitly

ONLY for run workouts (not bike, not swim), always append a structured upload block at the very end of your response:
[WORKOUT_UPLOAD]
name: <workout name>
---
<plain text workout in Intervals.icu format>
[/WORKOUT_UPLOAD]

Do NOT include this block for bike or swim workouts. It is only for runs.
This block will be stripped before the athlete sees the message and used to upload to Intervals.icu on confirm.

## Your Task
Recommend tomorrow's training session. Be specific and practical.

Respond in this exact format:

**RECOMMENDATION**: [Rest / Easy / Moderate / Hard]
**SPORT**: [Bike / Run / Swim / Rest / Cross-train]
**DURATION**: [e.g. 60 min]
**WORKOUT**:
[Structured workout. For runs: pace primary, RPE secondary, HR confirmatory. For bikes: power zones primary, HR secondary.]

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


def generate_swim_workout(duration_min, phase_name):
    """Generate swim workout in Intervals.icu plain text format.
    CSS threshold pace: 2:00/100m. Easy: 2:15-2:20/100m."""
    if phase_name in ["Base 1", "Base 2", "Late Base"]:
        return """Warmup
- 200m easy 2:20/100m

Drills
- 4x50m drill (catch-up or fingertip drag), 15s rest

Main set
- 8x100m @2:10/100m, 20s rest
- Focus: consistent splits, relaxed stroke

Cooldown
- 200m easy choice stroke"""
    elif phase_name in ["Build 1", "Build 2"]:
        return """Warmup
- 300m easy 2:20/100m

Main set
- 4x200m @2:05/100m, 30s rest
- 4x50m fast @1:55/100m, 20s rest

Cooldown
- 200m easy"""
    else:
        # Peak / Taper
        return """Warmup
- 200m easy

Main set
- 3x300m @2:00/100m (race pace), 45s rest

Cooldown
- 100m easy"""


def generate_run_workout_text(run_type):
    """Generate run workout in Intervals.icu plain text format based on type."""
    t = run_type.lower()
    if "tempo" in t:
        return """Warmup easy RPE3
- 10m 6:10/km

Tempo RPE6-7 HR154-162
- 3x 10m 5:05-5:20/km
- 3m 6:10/km recovery between

Cooldown RPE2
- 10m 6:30/km"""
    elif "long" in t:
        return """Warmup easy RPE3
- 10m 6:10/km

Long Z2 RPE3
- 60m 5:50-6:10/km, fully conversational
- HR confirms 145-153 after warmup

Cooldown RPE2
- 5m walk or very easy"""
    else:
        # Easy / Z2 default
        return """Warmup easy RPE3
- 10m 6:10/km

Easy Z2 RPE3
- 30m 5:50-6:10/km, fully conversational
- HR confirms 145-153 after 2min

Cooldown RPE2
- 5m 6:30/km"""


def get_weekly_plan(garmin_summary, intervals_summary, ctl_data, weekly):
    """Generate a 7-day training plan for the upcoming week.

    Returns the full Claude response text which contains:
    - Display plan (sent to athlete)
    - [PLAN_JSON]...[/PLAN_JSON] block (parsed separately, stripped before sending)
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    from utils import get_system_time_block
    from intervals_client import get_workout_library, get_current_phase_targets

    workout_library = get_workout_library()
    workout_library_text = "\n".join([
        f"- {w['zone']} | IF {w['median_if']} | NP {w['median_np']}W | TSS {w['median_tss']} | {w['median_duration_min']}min | {w['name']}"
        for w in workout_library
    ])

    phase = get_current_phase_targets()
    tss_min, tss_max = phase['tss_target']
    weeks_to_race = (date(2026, 6, 20) - date.today()).days // 7

    prompt = f"""{get_system_time_block()}

You are an expert triathlon coach. Generate a 7-day training plan for the upcoming week.
The week starts on weekly_plan_starts as specified in [SYSTEM_TIME] above.
Use that exact Monday date for all session dates.

## Athlete Context
- FTP: 291W | Run LTHR: 172 bpm | Swim threshold: 2:00/100m
- Phase: {phase['phase']} | TSS target: {tss_min}-{tss_max}/week
- CTL: {intervals_summary['ctl']} | ATL: {intervals_summary['atl']} | TSB: {intervals_summary['tsb']}
- CTL target at race: 48 | Gap: {round(48 - intervals_summary['ctl'], 1)} points
- Weekly structure: 3 bikes (2 structured + 1 Z2), 2 runs (1 easy + 1 tempo), 1 swim (Z2 aerobic), 1 rest day
- Priority: Bike > Run > Swim

## Last week
- Bike: {weekly.get('bike', {}).get('count', 0)}x {weekly.get('bike', {}).get('duration_min', 0)}min TSS {weekly.get('bike', {}).get('tss', 0)}
- Run: {weekly.get('run', {}).get('count', 0)}x {weekly.get('run', {}).get('duration_min', 0)}min TSS {weekly.get('run', {}).get('tss', 0)}
- Total TSS: {weekly.get('total_tss', 0)}

## Zwift Workout Library (bike sessions only — exact names required)
{workout_library_text}

## Run Prescription
- Easy/Z2: 5:50-6:10/km | RPE 3/10
- Tempo/Z3: 5:05-5:20/km | RPE 6-7/10
- Max 1 tempo run per week in base phase

## Output Rules
- Never put two hard sessions back to back
- Rest day on Friday or Monday preferred
- Longest bike on Saturday or Sunday
- Zwift workout names must come from library above exactly — never invent names
- For unstructured Z2 bike rides use "Free ride Zone 2"
- Total TSS must fall within {tss_min}-{tss_max}
- No column alignment — use clear labels (WhatsApp proportional font)
- Always include exactly 1 swim session per week

Respond in this exact format:

*Week of [Mon date] — {phase['phase']} | {weeks_to_race} weeks to Tremblant*
Target: {tss_min}-{tss_max} TSS | [one-line phase focus]

Mon: [Sport] — [Type] [duration] (~[TSS] TSS)[Zwift name if bike]
Tue: [Sport] — [Type] [duration] (~[TSS] TSS)[Zwift name if bike]
Wed: [Sport] — [Type] [duration] (~[TSS] TSS)[Zwift name if bike]
Thu: [Sport] — [Type] [duration] (~[TSS] TSS)
Fri: Rest
Sat: [Sport] — [Type] [duration] (~[TSS] TSS)[Zwift name if bike]
Sun: [Sport] — [Type] [duration] (~[TSS] TSS)

Total: [N] sessions | ~[H:MM] | ~[TSS] TSS

Reply with a change request to adjust e.g. "make Wednesday easier" or "swap Thu and Fri"
Reply "confirm plan" to upload all sessions to Intervals.icu and sync to Garmin

Then append this machine-readable block — it is stripped before the athlete sees the message:

[PLAN_JSON]
{{"week_start": "YYYY-MM-DD", "sessions": [
  {{"day": "Monday", "date": "YYYY-MM-DD", "sport": "Bike", "type": "Tempo", "duration_min": 60, "tss": 67, "zwift_workout": "exact name from library or Free ride Zone 2"}},
  {{"day": "Tuesday", "date": "YYYY-MM-DD", "sport": "Run", "type": "Easy", "duration_min": 45, "tss": 35}},
  {{"day": "Wednesday", "date": "YYYY-MM-DD", "sport": "Bike", "type": "Z2", "duration_min": 90, "tss": 58, "zwift_workout": "exact name"}},
  {{"day": "Thursday", "date": "YYYY-MM-DD", "sport": "Swim", "type": "Z2 Aerobic", "duration_min": 45, "tss": 30}},
  {{"day": "Friday", "date": "YYYY-MM-DD", "sport": "Rest", "type": "Rest", "duration_min": 0, "tss": 0}},
  {{"day": "Saturday", "date": "YYYY-MM-DD", "sport": "Bike", "type": "Z2 Long", "duration_min": 120, "tss": 80, "zwift_workout": "exact name"}},
  {{"day": "Sunday", "date": "YYYY-MM-DD", "sport": "Run", "type": "Tempo", "duration_min": 50, "tss": 55}}
], "total_tss": 325}}
[/PLAN_JSON]

Rules for the JSON block:
- Use the exact Monday date from weekly_plan_starts for "week_start" and increment by 1 day per session
- sport must be exactly "Bike", "Run", "Swim", or "Rest"
- zwift_workout must be the exact Zwift library name for Bike sessions (or "Free ride Zone 2")
- Do not include zwift_workout for Run, Swim, or Rest sessions
- Output valid JSON only — no trailing commas
"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text