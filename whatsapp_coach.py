from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
import anthropic
import os
import json
import time
import re
import threading
from datetime import date, timedelta
from dotenv import load_dotenv
from garmin_client import get_readiness_data
from intervals_client import get_fitness_data, get_workout_library, get_ctl_trajectory, get_weekly_summary, create_run_workout, get_most_recent_activity, save_activity_rpe, get_recent_rpe_data, format_ctl_report, format_weekly_summary, get_current_phase_targets, PHASE_DESCRIPTIONS, CTL_RACE_TARGET
from coach import summarize_garmin, summarize_intervals
from utils import get_system_time_block

load_dotenv()

app = Flask(__name__)

# In-memory conversation state per user
conversations = {}

FEEL_MAP = {"weak": 1, "poor": 2, "normal": 3, "good": 4, "strong": 5}

WEEKLY_PLAN_TRIGGERS = [
    "weekly plan", "plan my week", "what's my week",
    "give me a plan", "plan this week", "week plan",
    "plan for the week", "my plan",
]


def _ensure_conversation(phone_number):
    """Initialize conversation state dict if not already present."""
    if phone_number not in conversations:
        conversations[phone_number] = {
            "history": [],
            "pending_workout": None,
            "pending_weekly_plan": None,
            "post_workout_state": None,
            "post_workout_rpe": None,
            "post_workout_activity_id": None,
            "post_workout_activity_type": None,
        }

# Cache for slow data (refreshed hourly at most)
_cache = {
    "workout_library_text": None,
    "system_prompt": None,
    "ctl_data": None,
    "rpe_data": None,
    "last_refreshed": 0,
}
CACHE_TTL_SECONDS = 3600  # 1 hour

RACE_DATE = date(2026, 6, 20)


def get_training_phase(weeks_to_race=None):
    """Return current training phase name and description based on periodization timeline."""
    phase = get_current_phase_targets()
    phase_name = phase["phase"]
    tss_lo, tss_hi = phase["tss_target"]
    base_desc = PHASE_DESCRIPTIONS.get(phase_name, "")
    description = f"{base_desc} Target {tss_lo}-{tss_hi} TSS/wk."
    return phase_name, description


def refresh_cache():
    """Fetch slow data and rebuild system prompt. Called at startup and hourly."""
    now = time.time()
    print("Refreshing cache (workout library + CTL trajectory)...")

    try:
        workout_library = get_workout_library()
        workout_library_text = "\n".join([
            f"- {w['zone']} | IF {w['median_if']} | NP {w['median_np']}W | TSS {w['median_tss']} | {w['median_duration_min']}min | {w['name']}"
            for w in workout_library
        ])
        _cache["workout_library_text"] = workout_library_text
        print("OK Workout library loaded")
    except Exception as e:
        print(f"Workout library error: {e}")
        workout_library_text = _cache["workout_library_text"] or "(library unavailable)"

    try:
        ctl_data = get_ctl_trajectory()
        _cache["ctl_data"] = ctl_data
        print("OK CTL trajectory loaded")
    except Exception as e:
        print(f"CTL trajectory error: {e}")
        ctl_data = _cache["ctl_data"] or {}

    try:
        _cache["rpe_data"] = get_recent_rpe_data()
        print("OK RPE data loaded")
    except Exception as e:
        print(f"RPE data error: {e}")

    _cache["system_prompt"] = build_system_prompt(workout_library_text)
    _cache["last_refreshed"] = now
    print("Cache refresh complete.")


def get_cached():
    """Return cached data, refreshing if stale."""
    now = time.time()
    if _cache["system_prompt"] and (now - _cache["last_refreshed"]) < CACHE_TTL_SECONDS:
        return _cache["system_prompt"], _cache["ctl_data"]
    refresh_cache()
    return _cache["system_prompt"], _cache["ctl_data"]


def build_system_prompt(workout_library_text):
    weeks_to_race = (RACE_DATE - date.today()).days // 7
    phase_name, phase_description = get_training_phase(weeks_to_race)

    return f"""You are Coach Claude, an expert triathlon coach for Gaël, an experienced triathlete training for Tremblant 5150 (Olympic distance) on June 20, 2026.

## Athlete Profile
- Age: 44, Male, 75kg, Montreal-based
- Previous best at Tremblant 5150: 2:44:39 (9th age group)
  - Swim: 0:28:39 | Bike: 1:16:33 | Run: 0:51:00
- Goal: Top 5 age group finish
- Key limiters: bike power (FTP), run off-bike, swim efficiency
- Current phase: {phase_name} — {phase_description}
- Equipment: Zwift (indoor bike), outdoor/treadmill run, alpine skiing (cross-training)

## Athlete Physiology
- Bike FTP: 291W (confirmed ramp test)
- Bike LTHR: 172 bpm | Max HR: 190 bpm
- Bike power zones: Z1 <160W | Z2 160-218W | Z3 218-262W | Z4 262-305W | Z5 305-349W | Z6 349-436W | Z7 436W+
- Run LTHR: 172 bpm
- Run HR zones (confirmatory only): Z1 <145 | Z2 145-153 | Z3 154-162 | Z4 163-171
- Swim threshold pace: 2:00/100m

## Run Prescription Philosophy
- Pace is PRIMARY, RPE is SECONDARY, HR is CONFIRMATORY only
- HR lags pace by 60-90 seconds — never tell athlete to chase HR in real time
- Easy runs: 5:50-6:10/km | RPE 3/10 | HR confirms 145-153 after warmup
- Tempo runs: 5:05-5:20/km | RPE 6-7/10 | HR confirms 154-162 after 90s
- Threshold: 4:45-5:00/km | RPE 8/10 | HR confirms 163-171 after 90s
- Always note HR lag explicitly for interval work

## Zwift Workout Library (ONLY recommend from this list for bike sessions)
{workout_library_text}

CRITICAL: For bike sessions you MUST recommend a workout from the library above — exact name as listed.
Never invent or guess workout names. Match zone to prescribed intensity.
If only a Z2 ride is needed, say "free ride Zone 2" — do NOT invent a structured workout name.

## Run Workout Upload Format
ONLY when recommending a RUN workout (not bike, not swim), ALWAYS include this block at the very end:
[WORKOUT_UPLOAD]
name: <concise workout name>
---
<workout in Intervals.icu plain text format>
[/WORKOUT_UPLOAD]

Do NOT include this block for bike or swim sessions.

Intervals.icu plain text format example:
Warmup
- 10m 6:10/km, RPE 3/10 conversational

Main set
- 30m 5:50-6:00/km, RPE 3/10 fully conversational. HR confirms 145-153 after 2min

Cooldown
- 10m 6:30/km, RPE 2/10 very easy

For intervals use:
Main set 3x
- 8m 5:05-5:20/km, RPE 6-7/10. HR confirms 154-162 after 90s
- 3m 6:10/km, RPE 3/10 recovery

## Date and Time Rules
- The [SYSTEM_TIME] block in the most recent user message is always the authoritative date/time
- workout_recommendation_target_date is the ONLY date to use for workout recommendations
- Always recommend workouts for workout_recommendation_target_date — never for any other date
- Dates in earlier conversation history may be stale — always defer to the most recent [SYSTEM_TIME] block
- Never infer or calculate dates yourself — use only what is provided in [SYSTEM_TIME]

## Your Coaching Style
- Conversational but precise — like a coach texting an athlete
- Keep responses concise for WhatsApp (no walls of text)
- No emojis
- Always ask about energy level (1-5) and available time before prescribing a workout if you don't have that info
- When asked for training block overview: current phase, weeks to race, CTL progress, 3-day outlook
- Adapt recommendations based on how the athlete says they feel

## Response Format for Workout Requests
1. One-line block/phase context
2. Today's workout with structure (zones, power targets for bike / pace + RPE for run)
3. Zwift workout name if bike (from library only) OR [WORKOUT_UPLOAD] block if run
4. Brief rationale (1-2 sentences)
5. For runs: end with "Reply 'confirm' to upload to Intervals.icu and sync to your Garmin"

## Conversation Flow
- Hi/hello → ask how they're feeling and what they have time for
- Workout request without energy/time → ask first
- Energy + time given → give full recommendation
- Block/plan question → 3-day outlook and block overview
- Workout completed → acknowledge, note it, adjust outlook
"""


def get_coaching_context():
    """Fetch only fast/fresh data per message: Garmin, activities, weekly summary."""
    garmin_summary = {}
    intervals_summary = {"ctl": "unknown", "atl": "unknown", "tsb": "unknown", "recent_activities": []}
    weekly = {}

    try:
        garmin_data = get_readiness_data()
        garmin_summary = summarize_garmin(garmin_data)
    except Exception as e:
        print(f"Garmin fetch error: {e}")

    try:
        intervals_data = get_fitness_data()
        intervals_summary = summarize_intervals(intervals_data)
    except Exception as e:
        print(f"Intervals activities fetch error: {e}")

    try:
        weekly = get_weekly_summary()
    except Exception as e:
        print(f"Intervals weekly summary fetch error: {e}")

    return garmin_summary, intervals_summary, weekly


def extract_workout_upload(text):
    """Extract workout name and text from [WORKOUT_UPLOAD]...[/WORKOUT_UPLOAD] block."""
    match = re.search(r'\[WORKOUT_UPLOAD\](.*?)\[/WORKOUT_UPLOAD\]', text, re.DOTALL)
    if not match:
        return None, None

    content = match.group(1).strip()
    lines = content.split('\n')

    name = None
    workout_lines = []
    past_separator = False

    for line in lines:
        line = line.strip()
        if line.startswith('name:'):
            name = line.replace('name:', '').strip()
        elif line == '---':
            past_separator = True
        elif past_separator:
            workout_lines.append(line)

    workout_text = '\n'.join(workout_lines).strip()
    return name, workout_text


def strip_workout_upload_block(text):
    """Remove the [WORKOUT_UPLOAD] block from coach response before sending to athlete."""
    return re.sub(r'\[WORKOUT_UPLOAD\].*?\[/WORKOUT_UPLOAD\]', '', text, flags=re.DOTALL).strip()


def _format_rpe_block(rpe_data):
    """Format cached RPE data for injection into the context block."""
    if not rpe_data:
        return ""
    lines = ["Recent RPE (last 14 days):"]
    for entry in rpe_data:
        feel_str = f" | feel: {entry['feel']}" if entry.get("feel") else ""
        tss_str = f" | TSS {entry['tss']}" if entry.get("tss") else ""
        lines.append(f"{entry['date']} | {entry['type']}{tss_str} | RPE {entry['rpe']}{feel_str}")
    return "\n".join(lines)


def build_context_block(garmin_summary, intervals_summary, weekly, ctl_data, user_message=None):
    """Build the live data context block."""
    today_date = date.today()

    # Remaining days in the week (Sun=6, so days left after today = 6 - weekday())
    days_remaining = 6 - today_date.weekday()
    remaining_day_names = [
        (today_date + timedelta(days=i)).strftime("%A")
        for i in range(1, days_remaining + 1)
    ]
    remaining_days_str = f"{days_remaining} days remaining this week: {', '.join(remaining_day_names)}" if remaining_day_names else "today is the last day of the week (Sunday)"

    weeks_to_race = (RACE_DATE - today_date).days // 7
    days_to_race = (RACE_DATE - today_date).days
    weeks_remaining_for_ctl = max(weeks_to_race - 2, 1)
    phase_name, phase_description = get_training_phase(weeks_to_race)

    ctl_trend_yoy = ctl_data.get('yoy', {})
    total_tss = weekly.get('total_tss', 0)

    block = f"""{get_system_time_block()}

[LIVE DATA]
{remaining_days_str}.
Weeks to race: {weeks_to_race} ({days_to_race} days until June 20, 2026)
Current phase: {phase_name} — {phase_description}
Sleep: {garmin_summary.get('sleep_duration_hours')}hrs, score {garmin_summary.get('sleep_score')}
Deep sleep: {garmin_summary.get('deep_sleep_hours')}hrs | REM: {garmin_summary.get('rem_sleep_hours')}hrs
HRV last night: {garmin_summary.get('hrv_last_night')} | Weekly avg: {garmin_summary.get('hrv_weekly_avg')} | Status: {garmin_summary.get('hrv_status')}
CTL: {intervals_summary['ctl']} | ATL: {intervals_summary['atl']} | TSB: {intervals_summary['tsb']}
CTL progress: {ctl_data.get('ctl_progress_pct', 0)}% to target | current pace +{ctl_data.get('current_weekly_gain', 0)}/wk | need +{ctl_data.get('ctl_per_week_needed', 0)}/wk
Race-day projection at current pace: CTL {ctl_data.get('projected_race_ctl', 'N/A')} (target {ctl_data.get('ctl_target', CTL_RACE_TARGET)})
Weekly TSS needed: ~{ctl_data.get('weekly_tss_needed', 'N/A')} | This week so far: {total_tss}
4-week outlook: CTL {ctl_data.get('projected_ctl_4w_current', 'N/A')} at current pace vs {ctl_data.get('projected_ctl_4w_required', 'N/A')} needed
YoY CTL: 2024={ctl_trend_yoy.get('2024')} | 2025={ctl_trend_yoy.get('2025')} | 2026={ctl_data.get('current_ctl')} (current)
Week so far (since {weekly.get('week_start', 'N/A')}): Bike {weekly.get('bike', {}).get('count', 0)}x {weekly.get('bike', {}).get('duration_min', 0)}min TSS {weekly.get('bike', {}).get('tss', 0)} | Run {weekly.get('run', {}).get('count', 0)}x {weekly.get('run', {}).get('duration_min', 0)}min TSS {weekly.get('run', {}).get('tss', 0)} | Swim {weekly.get('swim', {}).get('count', 0)}x | Other {weekly.get('other', {}).get('count', 0)}x {weekly.get('other', {}).get('duration_min', 0)}min | Total TSS {total_tss} ({weekly.get('days_done', 0)}/7 days)
Recent activities: {json.dumps(intervals_summary['recent_activities'], default=str)}
{_format_rpe_block(_cache.get('rpe_data'))}"""
    if user_message:
        block += f"\n[ATHLETE MESSAGE]\n{user_message}\n"
    else:
        block += "\n[TASK]\nGenerate tomorrow's workout recommendation as a proactive nightly WhatsApp message. Be concise — opening line with phase/countdown, workout with pace+RPE for runs or power zones for bike, Zwift workout name if bike (from library only), one sentence rationale. Under 250 words. For runs include [WORKOUT_UPLOAD] block. End with: 'Reply confirm to upload to Garmin or reply to adjust'\n"

    return block


WEEKLY_REPORT_TRIGGERS = {
    "weekly report", "weekly summary", "how's my week",
    "weekly recap", "how am i tracking", "give me my week",
}


def chat_with_coach(user_message, phone_number, garmin_summary, intervals_summary, weekly, ctl_data, system_prompt):
    """Send message to Claude with full context and conversation history."""

    # Weekly summary: return structured format directly — no Claude generation
    if user_message.lower().strip() in WEEKLY_REPORT_TRIGGERS and ctl_data:
        augmented_ctl = dict(ctl_data)
        augmented_ctl['atl'] = intervals_summary.get('atl')
        augmented_ctl['tsb'] = intervals_summary.get('tsb')
        return format_weekly_summary(weekly, augmented_ctl)

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    _ensure_conversation(phone_number)

    history = conversations[phone_number]["history"]
    context_block = build_context_block(garmin_summary, intervals_summary, weekly, ctl_data, user_message)
    history.append({"role": "user", "content": context_block})

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=800,
        system=system_prompt,
        messages=history
    )

    full_reply = response.content[0].text

    # Extract and store workout upload block if present
    workout_name, workout_text = extract_workout_upload(full_reply)
    if workout_name and workout_text:
        conversations[phone_number]["pending_workout"] = {
            "name": workout_name,
            "text": workout_text
        }
        print(f"Stored pending upload for {phone_number}: {workout_name}")

    # Strip upload block before sending to athlete
    reply = strip_workout_upload_block(full_reply)

    history.append({"role": "assistant", "content": full_reply})  # keep full reply in history

    if len(history) > 8:
        conversations[phone_number]["history"] = history[-8:]

    return reply


def handle_confirm(phone_number):
    """Upload pending workout to Intervals.icu when athlete confirms."""
    _ensure_conversation(phone_number)
    pending = conversations[phone_number]["pending_workout"]
    if not pending:
        return "No pending workout to upload. Ask for a run recommendation first."

    try:
        result = create_run_workout(pending["name"], pending["text"])
        conversations[phone_number]["pending_workout"] = None
        return f"Done — '{result['name']}' uploaded to Intervals.icu ({result['steps']} steps). It will sync to your Garmin within a few minutes."
    except Exception as e:
        print(f"Upload error: {e}")
        return f"Upload failed: {str(e)}. Try again or check Intervals.icu manually."


def send_whatsapp_message(to, body):
    """Send outbound WhatsApp message via Twilio."""
    twilio = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    message = twilio.messages.create(
        from_=os.getenv("TWILIO_WHATSAPP_FROM"),
        to=to,
        body=body
    )
    print(f"Sent message SID: {message.sid}")
    return message.sid


def generate_nightly_message(garmin_summary, intervals_summary, weekly, ctl_data, system_prompt):
    """Generate tomorrow's workout as a standalone proactive message."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    context_block = build_context_block(garmin_summary, intervals_summary, weekly, ctl_data)

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": context_block}]
    )

    full_reply = response.content[0].text
    athlete_phone = os.getenv("ATHLETE_PHONE")

    # Store pending upload from nightly message
    workout_name, workout_text = extract_workout_upload(full_reply)
    if workout_name and workout_text:
        _ensure_conversation(athlete_phone)
        conversations[athlete_phone]["pending_workout"] = {
            "name": workout_name,
            "text": workout_text
        }
        print(f"Nightly: stored pending upload: {workout_name}")

    message = strip_workout_upload_block(full_reply)

    # Append compact CTL progress bar
    pct = ctl_data.get('ctl_progress_pct', 0)
    filled = min(int(pct / 5), 19)
    bar = "=" * filled + ">" + " " * (20 - filled - 1)
    ctl_line = (
        f"\nCTL [{bar}] {ctl_data.get('current_ctl')}/{ctl_data.get('ctl_target', CTL_RACE_TARGET)}"
        f" | +{ctl_data.get('current_weekly_gain', 0)} this week"
        f" | need +{ctl_data.get('ctl_per_week_needed', 0)}/wk"
    )
    return message + ctl_line


WORKOUT_DONE_TRIGGERS = {"workout done", "done", "finished", "completed workout"}


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")
    msg_lower = incoming_msg.lower()

    print(f"Message from {from_number}: {incoming_msg}")

    # Ensure conversation state exists for this number
    _ensure_conversation(from_number)

    # Handle confirm/upload trigger
    if msg_lower in ["confirm", "upload", "yes upload", "upload it"]:
        reply = handle_confirm(from_number)
        print(f"Upload reply: {reply}")
        resp = MessagingResponse()
        resp.message(reply)
        return str(resp)

    # Post-workout RPE capture state machine
    state = conversations[from_number]["post_workout_state"]

    if state == "awaiting_rpe":
        try:
            rpe = int(msg_lower.strip())
            if 1 <= rpe <= 10:
                conversations[from_number]["post_workout_rpe"] = rpe
                conversations[from_number]["post_workout_state"] = "awaiting_feel"
                reply = "How did your body feel? (weak / poor / normal / good / strong)"
                resp = MessagingResponse()
                resp.message(reply)
                return str(resp)
        except ValueError:
            pass
        resp = MessagingResponse()
        resp.message("Please reply with a number from 1 to 10.")
        return str(resp)

    if state == "awaiting_feel":
        feel_word = msg_lower.strip()
        if feel_word in FEEL_MAP:
            feel_int = FEEL_MAP[feel_word]
            rpe = conversations[from_number]["post_workout_rpe"]
            activity_id = conversations[from_number]["post_workout_activity_id"]
            activity_type = conversations[from_number]["post_workout_activity_type"] or "workout"
            # Reset post-workout state
            conversations[from_number]["post_workout_state"] = None
            conversations[from_number]["post_workout_rpe"] = None
            conversations[from_number]["post_workout_activity_id"] = None
            conversations[from_number]["post_workout_activity_type"] = None

            try:
                save_activity_rpe(activity_id, rpe, feel_int)
                # Invalidate RPE cache so next refresh picks up the new data
                _cache["rpe_data"] = None
            except Exception as e:
                print(f"RPE save error: {e}")

            # Route through Claude for the one-line coaching note
            garmin_summary, intervals_summary, weekly = get_coaching_context()
            system_prompt, ctl_data = get_cached()
            note_prompt = (
                f"[POST-WORKOUT LOGGED] Activity: {activity_type} | "
                f"RPE: {rpe}/10 | Feel: {feel_word} ({feel_int}/5). "
                f"Saved to Intervals.icu. Give a single coaching sentence acknowledging this effort "
                f"in context of current training load. No workout recommendation."
            )
            coach_note = chat_with_coach(
                note_prompt, from_number,
                garmin_summary, intervals_summary,
                weekly, ctl_data, system_prompt
            )
            reply = f"Logged — RPE {rpe}/10, feel: {feel_word}.\n{coach_note}"
            resp = MessagingResponse()
            resp.message(reply)
            return str(resp)
        else:
            resp = MessagingResponse()
            resp.message("Please reply with one of: weak / poor / normal / good / strong")
            return str(resp)

    # Workout-done trigger
    if msg_lower in WORKOUT_DONE_TRIGGERS:
        try:
            activity = get_most_recent_activity()
        except Exception as e:
            print(f"Post-workout activity lookup error: {e}")
            activity = None

        if activity:
            conversations[from_number]["post_workout_state"] = "awaiting_rpe"
            conversations[from_number]["post_workout_activity_id"] = activity["id"]
            conversations[from_number]["post_workout_activity_type"] = activity.get("type", "workout")
            conversations[from_number]["post_workout_rpe"] = None
            reply = "Nice work! Rate your effort 1-10 (1=very easy, 10=maximal):"
        else:
            reply = "Nice work! No recent activity found in Intervals.icu — make sure it's synced, then try again."
        resp = MessagingResponse()
        resp.message(reply)
        return str(resp)

    # Weekly plan trigger — run in background to avoid Twilio timeout
    if any(trigger in msg_lower for trigger in WEEKLY_PLAN_TRIGGERS):
        resp = MessagingResponse()
        resp.message("Generating your weekly plan, give me a moment...")

        def send_weekly_plan():
            try:
                garmin_summary, intervals_summary, weekly = get_coaching_context()
                system_prompt, ctl_data = get_cached()
                from coach import get_weekly_plan
                plan = get_weekly_plan(garmin_summary, intervals_summary, ctl_data, weekly)
                _ensure_conversation(from_number)
                conversations[from_number]["pending_weekly_plan"] = plan
                conversations[from_number]["history"].append({"role": "assistant", "content": plan})
                send_whatsapp_message(from_number, plan)
            except Exception as e:
                print(f"Weekly plan error: {e}")
                send_whatsapp_message(from_number, "Sorry, had trouble generating your plan. Try again.")

        thread = threading.Thread(target=send_weekly_plan)
        thread.daemon = True
        thread.start()
        return str(resp)

    # Normal coaching flow
    garmin_summary, intervals_summary, weekly = get_coaching_context()
    system_prompt, ctl_data = get_cached()

    reply = chat_with_coach(
        incoming_msg, from_number,
        garmin_summary, intervals_summary,
        weekly, ctl_data, system_prompt
    )

    print(f"Coach reply: {reply}")

    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)


@app.route("/nightly", methods=["GET", "POST"])
def nightly_push():
    """Called by cron at 8pm ET to send tomorrow's workout."""
    print("Nightly push triggered...")

    def send_in_background():
        try:
            garmin_summary, intervals_summary, weekly = get_coaching_context()
            system_prompt, ctl_data = get_cached()
            message = generate_nightly_message(garmin_summary, intervals_summary, weekly, ctl_data, system_prompt)
            athlete_phone = os.getenv("ATHLETE_PHONE")
            send_whatsapp_message(athlete_phone, message)
            print(f"Nightly push sent to {athlete_phone}")
        except Exception as e:
            print(f"Nightly push background error: {e}")

    thread = threading.Thread(target=send_in_background)
    thread.daemon = True
    thread.start()

    return "Nightly push started", 200


@app.route("/health", methods=["GET"])
def health():
    return "Coach is alive!", 200


# Pre-warm cache at startup
print("Pre-warming cache at startup...")
try:
    refresh_cache()
except Exception as e:
    print(f"Startup cache warm failed (will retry on first request): {e}")


if __name__ == "__main__":
    print("Triathlon Coach WhatsApp Server starting...")
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)