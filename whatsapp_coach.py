from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import os
import json
import time
from datetime import date, timedelta
from dotenv import load_dotenv
from garmin_client import get_readiness_data
from intervals_client import get_fitness_data, get_workout_library, get_ctl_trajectory, get_weekly_summary
from coach import summarize_garmin, summarize_intervals

load_dotenv()

app = Flask(__name__)

# In-memory conversation state per user
conversations = {}

# Cache for slow data (refreshed hourly at most)
_cache = {
    "workout_library_text": None,
    "system_prompt": None,
    "ctl_data": None,
    "last_refreshed": 0,
}
CACHE_TTL_SECONDS = 3600  # 1 hour


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
        print("✓ Workout library loaded")
    except Exception as e:
        print(f"Workout library error: {e}")
        workout_library_text = _cache["workout_library_text"] or "(library unavailable)"

    try:
        ctl_data = get_ctl_trajectory()
        _cache["ctl_data"] = ctl_data
        print("✓ CTL trajectory loaded")
    except Exception as e:
        print(f"CTL trajectory error: {e}")
        ctl_data = _cache["ctl_data"] or {}

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
    return f"""You are Coach Claude, an expert triathlon coach for Gaël, an experienced triathlete training for Tremblant 5150 (Olympic distance) on June 20, 2026.

## Athlete Profile
- Age: 44, Male, 75kg, Montreal-based
- Previous best at Tremblant 5150: 2:44:39 (9th age group)
  - Swim: 0:28:39 | Bike: 1:16:33 | Run: 0:51:00
- Goal: Top 5 age group finish
- Key limiters: bike power (FTP), run off-bike, swim efficiency
- Current phase: Base building (winter). Bike > Run > Swim priority. Swim resumes April.
- Equipment: Zwift (indoor bike), outdoor/treadmill run, alpine skiing (cross-training)

## Athlete Physiology
- Bike FTP: 291W (confirmed ramp test)
- Bike LTHR: 172 bpm | Max HR: 190 bpm
- Bike power zones: Z1 <160W | Z2 160-218W | Z3 218-262W | Z4 262-305W | Z5 305-349W | Z6 349-436W | Z7 436W+
- Run LTHR: 172 bpm
- Run HR zones: Z1 <145 | Z2 145-153 | Z3 154-162 | Z4 163-171 | Z5 172-176 | Z6 177-181 | Z7 182-190
- Swim threshold pace: 2:00/100m

## Zwift Workout Library (ONLY recommend from this list for bike sessions)
{workout_library_text}

CRITICAL: For bike sessions you MUST recommend a workout from the library above — exact name as listed.
Never invent or guess workout names. Match zone to prescribed intensity.
If only a Z2 ride is needed, say "free ride Zone 2" — do NOT invent a structured workout name.

## Your Coaching Style
- Conversational but precise — like a coach texting an athlete
- Keep responses concise for WhatsApp (no walls of text)
- Use emojis sparingly but effectively
- Always ask about energy level (1-5) and available time before prescribing a workout if you don't have that info
- When asked for training block overview: current phase, weeks to race, CTL progress, 3-day outlook
- Adapt recommendations based on how the athlete says they feel

## Response Format for Workout Requests
1. One-line block/phase context
2. Today's workout with structure (zones, power targets, HR targets)
3. Zwift workout name if bike (from library only, or "free ride Zone 2")
4. Brief rationale (1-2 sentences)
5. Ask: "How does that sound? 💪"

## Conversation Flow
- Hi/hello → ask how they're feeling and what they have time for
- Workout request without energy/time → ask first
- Energy + time given → give full recommendation
- Block/plan question → 3-day outlook and block overview
- Workout completed → acknowledge, note it, adjust outlook
"""


def get_coaching_context():
    """Fetch only fast/fresh data per message: Garmin, activities, weekly summary."""
    try:
        garmin_data = get_readiness_data()
        intervals_data = get_fitness_data()
        garmin_summary = summarize_garmin(garmin_data)
        intervals_summary = summarize_intervals(intervals_data)
        weekly = get_weekly_summary()
        return garmin_summary, intervals_summary, weekly
    except Exception as e:
        print(f"Data fetch error: {e}")
        return {}, {"ctl": "unknown", "atl": "unknown", "tsb": "unknown", "recent_activities": []}, {}


def chat_with_coach(user_message, phone_number, garmin_summary, intervals_summary, weekly, ctl_data, system_prompt):
    """Send message to Claude with full context and conversation history."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if phone_number not in conversations:
        conversations[phone_number] = []

    history = conversations[phone_number]

    today = date.today().strftime("%A, %B %d, %Y")
    tomorrow = (date.today() + timedelta(days=1)).strftime("%A, %B %d, %Y")

    # CTL trend strings from cache
    ctl_trend_4w = " → ".join([str(v) for _, v in ctl_data.get('trend_4w', [])])
    ctl_trend_yoy = ctl_data.get('yoy', {})
    current_ctl = ctl_data.get('current_ctl') or 0
    ctl_gap = round(55 - current_ctl, 1)
    weeks_remaining = max(weeks_to_race - 2, 1)  # -2 for taper
    ctl_per_week_needed = round(ctl_gap / weeks_remaining, 1)


    context_block = f"""
[LIVE DATA - {today}]
Tomorrow is {tomorrow}. Workout recommendations are for tomorrow unless athlete specifies otherwise.
Sleep: {garmin_summary.get('sleep_duration_hours')}hrs, score {garmin_summary.get('sleep_score')}
Deep sleep: {garmin_summary.get('deep_sleep_hours')}hrs | REM: {garmin_summary.get('rem_sleep_hours')}hrs
HRV last night: {garmin_summary.get('hrv_last_night')} | Weekly avg: {garmin_summary.get('hrv_weekly_avg')} | Status: {garmin_summary.get('hrv_status')}
CTL: {intervals_summary['ctl']} | ATL: {intervals_summary['atl']} | TSB: {intervals_summary['tsb']}
CTL 4-week trend: {ctl_trend_4w} ({ctl_data.get('trend_4w_direction', 'N/A')})
YoY CTL: 2024={ctl_trend_yoy.get('2024')} | 2025={ctl_trend_yoy.get('2025')} | 2026={ctl_trend_yoy.get('2026')} (current)
CTL target: 55-60 by race week — need +{ctl_gap} points in {weeks_remaining} weeks (~+{ctl_per_week_needed}/week)
Week so far (since {weekly.get('week_start', 'N/A')}): Bike {weekly.get('bike', {}).get('count', 0)}x {weekly.get('bike', {}).get('duration_min', 0)}min TSS {weekly.get('bike', {}).get('tss', 0)} | Run {weekly.get('run', {}).get('count', 0)}x {weekly.get('run', {}).get('duration_min', 0)}min TSS {weekly.get('run', {}).get('tss', 0)} | Swim {weekly.get('swim', {}).get('count', 0)}x | Other {weekly.get('other', {}).get('count', 0)}x {weekly.get('other', {}).get('duration_min', 0)}min | Total TSS {weekly.get('total_tss', 0)} ({weekly.get('days_done', 0)}/7 days)
Recent activities: {json.dumps(intervals_summary['recent_activities'], default=str)}
race_date = date(2026, 6, 20)
weeks_to_race = (race_date - date.today()).days // 7
days_to_race = (race_date - date.today()).days
Weeks to race: {weeks_to_race} ({days_to_race} days until June 20, 2026)


[ATHLETE MESSAGE]
{user_message}
"""

    history.append({"role": "user", "content": context_block})

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        system=system_prompt,
        messages=history
    )

    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})

    # Keep last 20 messages
    if len(history) > 20:
        conversations[phone_number] = history[-20:]

    return reply


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")

    print(f"Message from {from_number}: {incoming_msg}")

    # Fast fetches only
    garmin_summary, intervals_summary, weekly = get_coaching_context()

    # Slow data from cache
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


@app.route("/health", methods=["GET"])
def health():
    return "Coach is alive!", 200


# Pre-warm cache at startup so first message is fast
print("Pre-warming cache at startup...")
try:
    refresh_cache()
except Exception as e:
    print(f"Startup cache warm failed (will retry on first request): {e}")


if __name__ == "__main__":
    print("🏊 Triathlon Coach WhatsApp Server starting...")
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
