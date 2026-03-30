# ============================================================================
# weekly_planner.py — Coach 2.0: Weekly Training Plan Generator
# ============================================================================
#
# HOW THIS WORKS:
#   1. Every Sunday at 8:00 am ET, Railway calls POST /weekly-plan
#   2. This module pulls fresh CTL/ATL/TSB + last 14 days from Intervals.icu
#   3. It asks Claude to build a 7-day plan using the workout library + rules
#   4. The plan is uploaded to Intervals.icu (Mon–Sun)
#   5. A WhatsApp summary is sent to you
#
# RETRY LOGIC:
#   If the job fails, it retries once after 30 minutes.
#   If it fails again, you receive a WhatsApp alert to trigger manually.
#
# MANUAL TRIGGER:
#   POST /weekly-plan  (can be called from Railway dashboard or phone)
#
# ============================================================================

import os
import json
import re
import base64
import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import anthropic

load_dotenv()

# Import everything we need from config — single source of truth
from config import (
    ATHLETE_NAME,
    FTP_WATTS,
    BIKE_LTHR,
    RUN_LTHR,
    MAX_HR,
    SWIM_THRESHOLD_PACE,
    RACE_DATE,
    RACE_NAME,
    CTL_TARGET,
    SCHEDULE,
    WORKOUT_LIBRARY,
    PERIODIZATION,
    PHASE_DESCRIPTIONS,
    DAY_TYPE_RULES,
    get_current_phase,
    weeks_to_race,
    is_race_specific_window,
)

_MONTREAL = ZoneInfo("America/Toronto")


# ─── INTERVALS.ICU HELPERS ───────────────────────────────────────────────────

def _icu_cfg():
    """Return auth headers + base URL for Intervals.icu API calls."""
    api_key    = os.getenv("INTERVALS_API_KEY")
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    return {
        "base_url":   "https://intervals.icu/api/v1",
        "athlete_id": athlete_id,
        "headers": {
            "Authorization":  f"Basic {token}",
            "Content-Type":   "application/json",
        },
    }


def _get_wellness(cfg, oldest, newest):
    """Fetch CTL/ATL/TSB wellness data for a date range."""
    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/wellness",
        headers=cfg["headers"],
        params={"oldest": oldest, "newest": newest},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _get_activities(cfg, oldest, newest):
    """Fetch recent activities with key training load fields."""
    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities",
        headers=cfg["headers"],
        params={
            "oldest": oldest,
            "newest": newest,
            "fields": "id,type,name,start_date_local,moving_time,distance,icu_training_load,average_heartrate,icu_intensity",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _check_existing_plan(cfg, monday_str, sunday_str):
    """
    Check if events already exist in Intervals.icu for next week.
    Returns a list of event names if any exist, empty list if the week is clear.
    """
    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events",
        headers=cfg["headers"],
        params={"oldest": monday_str, "newest": sunday_str},
        timeout=15,
    )
    if r.status_code == 200:
        events = r.json()
        return [e.get("name", "unnamed") for e in events if e.get("category") == "WORKOUT"]
    return []


def _delete_event(cfg, event_id):
    """Delete a single event from Intervals.icu (used when overwriting a plan)."""
    r = requests.delete(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events/{event_id}",
        headers=cfg["headers"],
        timeout=15,
    )
    # 204 = deleted, 404 = already gone — both are fine
    return r.status_code in (200, 204, 404)


def _upload_event(cfg, name, sport_type, date_str, description, category="WORKOUT"):
    """
    Post a single planned workout event to Intervals.icu.
    sport_type must be one of: Ride, Run, Swim
    Returns the created event dict (includes 'id').
    """
    payload = {
        "name":             name,
        "type":             sport_type,
        "category":         category,
        "start_date_local": f"{date_str}T00:00:00",
        "description":      description,
    }
    r = requests.post(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events",
        headers=cfg["headers"],
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ─── DATA PULL ───────────────────────────────────────────────────────────────

def pull_planning_data():
    """
    Pull everything Claude needs to build this week's plan.
    Returns a dict with: current_tsb, current_ctl, current_atl,
    last_14_days (list of activities), current_phase, weeks_left.
    Raises on hard failures (Intervals.icu down).
    """
    cfg   = _icu_cfg()
    today = datetime.now(_MONTREAL).date()

    # Wellness: last 3 days to get the freshest CTL/ATL/TSB
    wellness_oldest = (today - timedelta(days=3)).isoformat()
    wellness_newest = today.isoformat()
    wellness = _get_wellness(cfg, wellness_oldest, wellness_newest)

    # Extract latest non-null CTL/ATL/TSB
    ctl, atl, tsb = None, None, None
    for w in reversed(wellness):
        if w.get("ctl") is not None and ctl is None:
            ctl = round(w["ctl"], 1)
        if w.get("atl") is not None and atl is None:
            atl = round(w["atl"], 1)
        if w.get("tsb") is not None and tsb is None:
            tsb = round(w["tsb"], 1)
        if ctl and atl and tsb:
            break

    # Activities: last 14 days
    acts_oldest = (today - timedelta(days=14)).isoformat()
    acts_newest = (today + timedelta(days=1)).isoformat()
    activities  = _get_activities(cfg, acts_oldest, acts_newest)

    # Summarise activities for Claude (keep it concise)
    activity_summary = []
    for a in activities:
        duration_min = (a.get("moving_time") or 0) // 60
        tss = round(a.get("icu_training_load") or 0)
        activity_summary.append({
            "date":     a.get("start_date_local", "")[:10],
            "type":     a.get("type", ""),
            "name":     a.get("name", ""),
            "duration": duration_min,
            "tss":      tss,
        })

    return {
        "current_ctl":   ctl,
        "current_atl":   atl,
        "current_tsb":   tsb,
        "last_14_days":  activity_summary,
        "current_phase": get_current_phase(),
        "weeks_left":    weeks_to_race(),
        "race_specific_window": is_race_specific_window(),
    }


# ─── WORKOUT LIBRARY SUMMARY ─────────────────────────────────────────────────

def _build_library_summary():
    """
    Format the full workout library as a compact text block for Claude.
    Groups by sport and intensity so Claude can make smart selections.
    """
    by_sport = {"bike": [], "run": [], "swim": []}
    for w in WORKOUT_LIBRARY:
        sport = w.get("sport", "bike")
        if sport in by_sport:
            by_sport[sport].append(w)

    lines = []
    for sport, workouts in by_sport.items():
        lines.append(f"\n=== {sport.upper()} WORKOUTS ===")
        for w in workouts:
            race_flag = " [RACE-SPECIFIC: final 6 weeks only]" if w.get("race_specific") else ""
            phase_note = ""
            if w.get("phase_ok") and w["phase_ok"] != ["all"]:
                phase_note = f" [phases: {', '.join(w['phase_ok'])}]"
            lines.append(
                f"  • {w['name']}"
                f" | day_types: {', '.join(w['day_types'])}"
                f" | intensity: {w['intensity']}"
                f" | ~{w['duration_min']}min, TSS~{w['est_tss']}"
                f"{phase_note}{race_flag}"
                f"\n    {w['description']}"
            )
    return "\n".join(lines)


# ─── SWIM WORKOUT GENERATOR ───────────────────────────────────────────────────

def _swim_workout_for_phase(phase_name, tsb):
    """
    Return a (name, description) tuple for Wednesday's swim workout,
    appropriate for the current training phase and fatigue level.
    Swim workouts are generated as Intervals.icu plain-text format.
    """
    # If very fatigued, give an easier technical swim
    if tsb is not None and tsb < -20:
        return (
            "Swim — Technical Recovery",
            "Warmup\n- 400m easy, focus on long stroke\n\n"
            "Drill set\n- 4x50m catch-up drill, 20s rest\n- 4x50m fingertip drag drill, 20s rest\n\n"
            "Main set\n- 4x100m @2:15/100m, 30s rest\n- Stay smooth, no pushing\n\n"
            "Cooldown\n- 200m easy backstroke or choice"
        )

    # Phase-appropriate progressions
    if phase_name in ("Base 1", "Base 2"):
        return (
            "Swim — Z2 Aerobic Base",
            "Warmup\n- 300m easy, build last 100m\n\n"
            "Drill set\n- 4x50m catch-up drill, 20s rest\n\n"
            "Main set\n- 6x100m @2:10/100m, 25s rest\n- Focus: relaxed stroke, 16-18 strokes/length\n\n"
            "Cooldown\n- 200m easy"
        )
    elif phase_name == "Late Base":
        return (
            "Swim — Z2 Volume Build",
            "Warmup\n- 400m easy, build last 100m\n\n"
            "Drill set\n- 4x50m pull buoy only, 20s rest\n\n"
            "Main set\n- 8x100m @2:05/100m, 20s rest\n- Aim for even splits across all 8\n\n"
            "Cooldown\n- 200m easy"
        )
    elif phase_name in ("Build 1", "Build 2"):
        return (
            "Swim — Threshold Intervals",
            "Warmup\n- 400m easy\n- 4x50m drill (choice), 20s rest\n\n"
            "Main set\n- 4x200m @2:00/100m pace, 30s rest\n- Hold target pace every rep — not faster early\n- RPE 6–7/10\n\n"
            "Cooldown\n- 300m easy, focus on long stroke"
        )
    elif phase_name == "Peak":
        return (
            "Swim — Race-Pace Intervals",
            "Warmup\n- 400m easy\n- 4x50m build to race pace, 20s rest\n\n"
            "Main set\n- 5x200m @1:58/100m, 25s rest\n- Race-pace effort, controlled breathing\n- RPE 7–8/10\n\n"
            "Threshold finisher\n- 400m straight at 2:00/100m target pace\n\n"
            "Cooldown\n- 200m easy"
        )
    elif phase_name in ("Taper 1", "Race Week"):
        return (
            "Swim — Race Sharpener",
            "Warmup\n- 300m easy\n- 4x50m fast (15s rest), back to easy\n\n"
            "Main set\n- 4x100m @1:55/100m, 30s rest\n- Sharp and confident, not exhausting\n\n"
            "Cooldown\n- 200m easy"
        )
    else:
        # Fallback
        return (
            "Swim — Z2 Aerobic",
            "Warmup\n- 300m easy\n\n"
            "Main set\n- 6x100m @2:05/100m, 25s rest\n- Even effort, relaxed stroke\n\n"
            "Cooldown\n- 200m easy"
        )


# ─── CLAUDE PLAN GENERATION ──────────────────────────────────────────────────

def _build_claude_prompt(data):
    """
    Build the system + user prompt for Claude to generate the weekly plan.
    Returns (system_prompt, user_message) tuple.
    """
    phase       = data["current_phase"]
    phase_name  = phase["phase"]
    tss_lo, tss_hi = phase["tss_target"]
    ctl_lo, ctl_hi = phase["ctl_target"]
    weeks_left  = data["weeks_left"]
    tsb         = data["current_tsb"]
    ctl         = data["current_ctl"]
    race_window = data["race_specific_window"]

    # Next Monday as the plan start
    today      = datetime.now(_MONTREAL).date()
    days_to_monday = (7 - today.weekday()) % 7
    if days_to_monday == 0:
        days_to_monday = 7
    next_monday = today + timedelta(days=days_to_monday)
    week_dates  = {
        "monday":    (next_monday).isoformat(),
        "tuesday":   (next_monday + timedelta(days=1)).isoformat(),
        "wednesday": (next_monday + timedelta(days=2)).isoformat(),
        "thursday":  (next_monday + timedelta(days=3)).isoformat(),
        "friday":    (next_monday + timedelta(days=4)).isoformat(),
        "saturday":  (next_monday + timedelta(days=5)).isoformat(),
        "sunday":    (next_monday + timedelta(days=6)).isoformat(),
    }

    library_text = _build_library_summary()

    # Format last 14 days activities
    recent_text = ""
    for a in data["last_14_days"]:
        recent_text += f"  {a['date']} | {a['type']:12} | {a['duration']}min | TSS {a['tss']} | {a['name']}\n"
    if not recent_text:
        recent_text = "  No recent activities recorded.\n"

    # TSB load-shedding guidance
    tsb_guidance = ""
    if tsb is not None:
        if tsb < -20:
            tsb_guidance = (
                f"⚠️ TSB is {tsb} (below -20). This athlete is carrying significant fatigue. "
                "Apply load-shedding rules: replace one QUALITY session with RECOVERY, "
                "shorten the LONG AEROBIC session. When choosing the RECOVERY sport, "
                "look at the last 3–4 days — if they've been running more, make it a bike recovery, "
                "and vice versa. Prioritise the sport they've done less of recently."
            )
        elif tsb > 10 and weeks_left <= 8:
            tsb_guidance = (
                f"TSB is {tsb} (above +10) and we're {weeks_left} weeks from race. "
                "Athlete is fresh — consider adding a QUALITY session if the week can support it "
                "without violating the consecutive-quality rule."
            )
        else:
            tsb_guidance = f"TSB is {tsb} — normal training week, no load adjustments needed."

    system_prompt = f"""You are a highly experienced triathlon coach working with {ATHLETE_NAME},
an age-group athlete targeting a top-5 finish at {RACE_NAME} on {RACE_DATE.strftime('%B %d, %Y')}.

ATHLETE CONSTANTS:
  FTP: {FTP_WATTS}W | Bike/Run LTHR: {BIKE_LTHR}/{RUN_LTHR} bpm | Max HR: {MAX_HR} bpm
  Swim threshold: {SWIM_THRESHOLD_PACE} | Weight: 75 kg
  Training philosophy: Norwegian Method / polarized 80/20
  Run coaching: pace is the primary metric (HR lags 60–90 sec on runs)

YOUR TASK:
Generate a 7-day training plan for the week of {next_monday.strftime('%B %d, %Y')}.
You must return ONLY a valid JSON object — nothing else, no explanation, no markdown fences.

OUTPUT FORMAT — return exactly this JSON structure:
{{
  "week_of": "{next_monday.isoformat()}",
  "weeks_to_race": {weeks_left},
  "total_tss": <integer — sum of all session TSS estimates>,
  "focus": "<one sentence on what this week is building toward>",
  "days": [
    {{
      "day": "Monday",
      "date": "{week_dates['monday']}",
      "day_type": "<one of: REST, RECOVERY, Z2 ENDURANCE, QUALITY, LONG AEROBIC, RACE-SPECIFIC>",
      "sport": "<Bike | Run | Swim | Rest>",
      "workout_name": "<exact name from library, or null for REST>",
      "description": "<one-line description for the WhatsApp summary>",
      "intervals_description": "<full workout text for Intervals.icu — structured steps>",
      "est_tss": <integer>,
      "duration_min": <integer>
    }},
    ... repeat for Tuesday through Sunday
  ]
}}

SCHEDULE CONSTRAINTS — you MUST respect these:
  Monday:    run or bike
  Tuesday:   run or bike
  Wednesday: swim (always — no exceptions)
  Thursday:  run or bike
  Friday:    run or bike
  Saturday:  long bike{' or brick' if race_window else ' (no bricks yet — not in race-specific window)'}
  Sunday:    long run

DAY-TYPE RULES:
  REST: complete rest, no training
  RECOVERY: Z1/Z2 easy spin or short easy run, under 45 min, HR below 140
  Z2 ENDURANCE: aerobic base, 60–90 min, strictly polarized
  QUALITY: threshold or above, pick one named workout from the library
  LONG AEROBIC: 90–150 min Z2, Saturday (bike) or Sunday (run)
  RACE-SPECIFIC: brick/transition/race-pace intervals — only if race_specific_window is True

PLANNING RULES — these are hard constraints:
  1. Maximum 2 QUALITY sessions per week, never on consecutive days
  2. Minimum 1 REST or RECOVERY day between any two QUALITY days
  3. LONG AEROBIC on Saturday or Sunday (not both)
  4. Never schedule QUALITY the day after a LONG AEROBIC
  5. Wednesday is ALWAYS swim — assign the swim workout Claude generates separately
  6. Saturday is LONG AEROBIC (bike) — pick a long aerobic bike workout from the library
  7. Sunday is LONG AEROBIC (run) — use NOR Run — Long Negative Split or similar
  8. {tsb_guidance}
  9. RACE-SPECIFIC sessions allowed: {race_window}
  10. For RECOVERY days: choose sport based on what the athlete did in the last 3–4 days
      (balance run/bike — if they ran more recently, recover on bike, and vice versa)

CURRENT TRAINING CONTEXT:
  Phase: {phase_name} — {PHASE_DESCRIPTIONS.get(phase_name, '')}
  CTL target this phase: {ctl_lo}–{ctl_hi} | Weekly TSS target: {tss_lo}–{tss_hi}
  Current CTL: {ctl} | ATL: {data['current_atl']} | TSB: {tsb}
  Weeks to {RACE_NAME}: {weeks_left}

LAST 14 DAYS OF TRAINING:
{recent_text}

WORKOUT LIBRARY (choose workout_name exactly as shown):
{library_text}

IMPORTANT: The 'intervals_description' field must be plain text in Intervals.icu format:
  Section headers (e.g. Warmup, Main set, Cooldown) followed by steps prefixed with "- "
  For bikes: reference power as % FTP or watts (FTP = {FTP_WATTS}W)
  For runs: reference pace in min/km and HR in bpm
  For swims: distance + pace per 100m

Return ONLY the JSON. No text before or after it."""

    user_message = f"""Generate the weekly training plan for {ATHLETE_NAME}.
Week: {next_monday.strftime('%B %d, %Y')} | Weeks to race: {weeks_left}
Current TSB: {tsb} | CTL: {ctl} | Phase: {phase_name}"""

    return system_prompt, user_message


def _call_claude(system_prompt, user_message):
    """
    Call Claude API to generate the weekly plan.
    Returns the raw response text.
    Raises on API failure.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _parse_plan(raw_text):
    """
    Parse Claude's JSON response into a plan dict.
    Tries direct JSON parse first; falls back to extracting JSON from text.
    Returns the plan dict, or raises ValueError if parsing fails.
    """
    text = raw_text.strip()

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON block from text (handles accidental prose wrapping)
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse Claude response as JSON. Raw text:\n{text[:500]}")


# ─── UPLOAD PLAN TO INTERVALS.ICU ────────────────────────────────────────────

def _upload_plan(plan, swim_name, swim_description):
    """
    Upload the 7-day plan to Intervals.icu.
    Wednesday's swim always uses the generated swim_name/swim_description.
    Returns (uploaded_count, errors_list).
    """
    cfg      = _icu_cfg()
    uploaded = 0
    errors   = []

    sport_type_map = {
        "Bike":  "Ride",
        "Run":   "Run",
        "Swim":  "Swim",
        "Rest":  None,   # skipped
    }

    for day in plan.get("days", []):
        sport    = day.get("sport", "Rest")
        day_name = day.get("day", "")
        date_str = day.get("date", "")

        if sport == "Rest" or day.get("day_type") in ("REST", "RECOVERY") and sport == "Rest":
            print(f"  {day_name}: Rest — skipped")
            continue

        # REST day_type with any sport = skip (e.g. a full rest day)
        if day.get("day_type") == "REST":
            print(f"  {day_name}: REST day — skipped")
            continue

        api_sport = sport_type_map.get(sport)
        if api_sport is None:
            print(f"  {day_name}: {sport} — skipped (unknown sport)")
            continue

        # Wednesday swim uses generated description, not Claude's
        if day_name == "Wednesday" and api_sport == "Swim":
            name        = swim_name
            description = swim_description
        else:
            name        = day.get("workout_name") or day.get("description") or f"{sport} session"
            description = day.get("intervals_description") or day.get("description") or ""

        try:
            result = _upload_event(cfg, name, api_sport, date_str, description)
            day["event_id"] = result.get("id")
            day["uploaded"] = True
            uploaded += 1
            print(f"  {day_name}: {name} — uploaded (id: {result.get('id')})")
        except Exception as e:
            errors.append(f"{day_name}: {sport} — {str(e)}")
            print(f"  {day_name}: UPLOAD FAILED — {e}")

    return uploaded, errors


# ─── WHATSAPP FORMATTING ─────────────────────────────────────────────────────

def _format_whatsapp_message(plan, week_date, weeks_left, upload_errors):
    """
    Format the WhatsApp summary in the exact format specified.
    week_date is the Monday of the plan week (date object).
    """
    day_lines = []
    for day in plan.get("days", []):
        day_name = day.get("day", "")
        day_type = day.get("day_type", "REST")
        desc     = day.get("description", "")

        # Abbreviate day name to 3 chars for compact display
        short_day = day_name[:3]
        day_lines.append(f"{short_day}: {day_type} — {desc}")

    days_block = "\n".join(day_lines)
    total_tss  = plan.get("total_tss", "?")
    focus      = plan.get("focus", "")

    # Error note if any uploads failed
    error_note = ""
    if upload_errors:
        error_note = f"\n\n⚠️ {len(upload_errors)} upload(s) failed — check Railway logs."

    msg = (
        f"📅 Week of {week_date.strftime('%B %d')} — {weeks_left} weeks to {RACE_NAME}\n\n"
        f"{days_block}\n\n"
        f"Load target: {total_tss} TSS\n"
        f"Focus: {focus}\n\n"
        f"Reply CHANGE + day to swap a workout.\n"
        f"Reply REST + day to make a day a rest day.{error_note}"
    )
    return msg


# ─── WHATSAPP SEND ────────────────────────────────────────────────────────────

def _send_whatsapp(message):
    """Send a WhatsApp message to the athlete via Twilio."""
    from twilio.rest import Client as TwilioClient

    client = TwilioClient(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN"),
    )
    client.messages.create(
        from_=os.getenv("TWILIO_WHATSAPP_FROM"),
        to=os.getenv("ATHLETE_PHONE"),
        body=message,
    )
    print("WhatsApp message sent.")


def _send_failure_alert(reason):
    """Send a failure alert WhatsApp so the athlete can trigger manually."""
    try:
        _send_whatsapp(
            f"⚠️ Weekly plan generation failed: {reason}\n\n"
            "Reply GO to trigger the plan manually."
        )
        print(f"Failure alert sent: {reason}")
    except Exception as e:
        # Last resort — log it so Railway shows it
        print(f"CRITICAL: Could not send failure alert: {e}")


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def generate_weekly_plan(overwrite_if_exists=False):
    """
    Full pipeline: pull data → generate plan → upload → WhatsApp.

    Returns a dict:
      { "success": bool, "message": str, "plan": dict or None, "errors": list }

    If the week already has a plan in Intervals.icu and overwrite_if_exists is False,
    returns success=False with a message explaining that — the caller (Flask route)
    should ask the athlete before re-running with overwrite_if_exists=True.
    """
    today       = datetime.now(_MONTREAL).date()
    days_to_mon = (7 - today.weekday()) % 7
    if days_to_mon == 0:
        days_to_mon = 7
    next_monday = today + timedelta(days=days_to_mon)
    next_sunday = next_monday + timedelta(days=6)

    print(f"\n=== Weekly Plan Generation — {next_monday} to {next_sunday} ===")

    # ── Step 1: Check for existing plan ──────────────────────────────────────
    try:
        cfg             = _icu_cfg()
        existing_events = _check_existing_plan(cfg, next_monday.isoformat(), next_sunday.isoformat())
        if existing_events and not overwrite_if_exists:
            names = ", ".join(existing_events[:3])
            if len(existing_events) > 3:
                names += f" (+{len(existing_events)-3} more)"
            print(f"Existing plan found: {names}")
            return {
                "success":  False,
                "message":  f"A plan already exists for the week of {next_monday} ({names}). Set overwrite=true to replace it.",
                "plan":     None,
                "errors":   [],
                "existing": existing_events,
            }
    except Exception as e:
        print(f"Warning: could not check for existing plan — {e}. Proceeding anyway.")

    # ── Step 2: Pull fresh data from Intervals.icu ───────────────────────────
    print("Pulling planning data from Intervals.icu...")
    try:
        data = pull_planning_data()
        print(f"  CTL: {data['current_ctl']} | ATL: {data['current_atl']} | TSB: {data['current_tsb']}")
        print(f"  Phase: {data['current_phase']['phase']} | Weeks to race: {data['weeks_left']}")
    except Exception as e:
        msg = f"Intervals.icu data pull failed: {e}"
        print(f"FAIL: {msg}")
        return {"success": False, "message": msg, "plan": None, "errors": [msg]}

    # ── Step 3: Generate swim workout for Wednesday ───────────────────────────
    swim_name, swim_description = _swim_workout_for_phase(
        data["current_phase"]["phase"],
        data["current_tsb"],
    )
    print(f"  Swim: {swim_name}")

    # ── Step 4: Build Claude prompt and generate plan ─────────────────────────
    print("Generating plan with Claude...")
    system_prompt, user_message = _build_claude_prompt(data)
    try:
        raw_response = _call_claude(system_prompt, user_message)
        print(f"  Claude response received ({len(raw_response)} chars)")
    except Exception as e:
        msg = f"Claude API failed: {e}"
        print(f"FAIL: {msg}")
        return {"success": False, "message": msg, "plan": None, "errors": [msg]}

    # ── Step 5: Parse the JSON plan ───────────────────────────────────────────
    try:
        plan = _parse_plan(raw_response)
        print(f"  Plan parsed: {len(plan.get('days', []))} days, TSS={plan.get('total_tss')}")
    except ValueError as e:
        msg = f"Plan parsing failed: {e}"
        print(f"FAIL: {msg}")
        return {"success": False, "message": msg, "plan": None, "errors": [msg]}

    # ── Step 6: Upload to Intervals.icu ──────────────────────────────────────
    print("Uploading to Intervals.icu...")
    uploaded, upload_errors = _upload_plan(plan, swim_name, swim_description)
    print(f"  {uploaded} sessions uploaded, {len(upload_errors)} errors")

    # ── Step 7: Send WhatsApp summary ─────────────────────────────────────────
    print("Sending WhatsApp summary...")
    msg = _format_whatsapp_message(plan, next_monday, data["weeks_left"], upload_errors)
    try:
        _send_whatsapp(msg)
    except Exception as e:
        print(f"WhatsApp send failed: {e}")
        # Don't fail the whole job if WA fails — plan is in Intervals.icu

    return {
        "success": True,
        "message": f"Plan generated and uploaded. {uploaded} sessions, {len(upload_errors)} errors.",
        "plan":    plan,
        "errors":  upload_errors,
    }
