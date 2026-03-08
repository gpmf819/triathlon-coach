from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import os
import json
from datetime import date
from dotenv import load_dotenv
from garmin_client import get_readiness_data
from intervals_client import get_fitness_data
from coach import summarize_garmin, summarize_intervals

load_dotenv()

app = Flask(__name__)

# In-memory conversation state per user
conversations = {}

def get_coaching_context():
    """Fetch all data and return a context summary for Claude."""
    try:
        garmin_data = get_readiness_data()
        intervals_data = get_fitness_data()
        garmin_summary = summarize_garmin(garmin_data)
        intervals_summary = summarize_intervals(intervals_data)
        return garmin_summary, intervals_summary
    except Exception as e:
        print(f"Data fetch error: {e}")
        return {}, {"ctl": "unknown", "atl": "unknown", "tsb": "unknown", "recent_activities": []}

SYSTEM_PROMPT = """You are Coach Claude, an expert triathlon coach for Gaël, an experienced triathlete training for Tremblant 5150 (Olympic distance) on June 20, 2026.

## Athlete Profile
- Age group: 40-44, Montreal-based
- Previous best at Tremblant 5150: 2:44:39 (9th age group)
  - Swim: 0:28:39 | Bike: 1:16:33 | Run: 0:51:00
- Goal: Top 5 age group finish
- Key limiters: bike power (FTP), run off-bike, swim efficiency
- Current phase: Base building (winter). Bike > Run > Swim priority. Swim resumes April.
- Equipment: Zwift (indoor bike), outdoor/treadmill run, alpine skiing (cross-training)

## Your Coaching Style
- Conversational but precise — like a coach texting an athlete
- Keep responses concise for WhatsApp (no walls of text)
- Use emojis sparingly but effectively
- When giving a workout, always include a specific Zwift workout name if it's a bike session
- Always ask about energy level (1-5) and available time before prescribing a workout if you don't have that info yet
- When asked for the training block overview, give: current phase, weeks to race, CTL progress, and 3-day outlook
- Adapt recommendations based on what the athlete tells you about how they feel

## Response Format for Workout Requests
When delivering a workout recommendation:
1. One-line block/phase context
2. Today's workout with structure
3. Zwift workout name if bike
4. Brief rationale (1-2 sentences)
5. Ask: "How does that sound? 💪"

## Conversation Flow
- If user says hi/hello/what's up → ask how they're feeling and what they have time for
- If user asks for workout → if you don't know energy/time, ask first
- If user gives energy + time → give the full workout recommendation
- If user asks about the block/plan → give the 3-day outlook and block overview
- If user says they did a workout → acknowledge, note it, adjust outlook
- Keep it natural — this is WhatsApp, not a report
"""

def chat_with_coach(user_message, phone_number, garmin_summary, intervals_summary):
    """Send message to Claude with full context and conversation history."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Get or create conversation history for this user
    if phone_number not in conversations:
        conversations[phone_number] = []

    history = conversations[phone_number]

    # Build context block to prepend to user message
    today = date.today().strftime("%A, %B %d")
    context_block = f"""
[LIVE DATA - {today}]
Sleep: {garmin_summary.get('sleep_duration_hours')}hrs, score {garmin_summary.get('sleep_score')}
Deep sleep: {garmin_summary.get('deep_sleep_hours')}hrs | REM: {garmin_summary.get('rem_sleep_hours')}hrs
HRV last night: {garmin_summary.get('hrv_last_night')} | Weekly avg: {garmin_summary.get('hrv_weekly_avg')} | Status: {garmin_summary.get('hrv_status')}
CTL: {intervals_summary['ctl']} | ATL: {intervals_summary['atl']} | TSB: {intervals_summary['tsb']}
Recent activities: {json.dumps(intervals_summary['recent_activities'], default=str)}
Weeks to race: 15

[ATHLETE MESSAGE]
{user_message}
"""

    history.append({"role": "user", "content": context_block})

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=history
    )

    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})

    # Keep conversation history to last 10 exchanges
    if len(history) > 20:
        conversations[phone_number] = history[-20:]

    return reply

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")

    print(f"Message from {from_number}: {incoming_msg}")

    # Fetch fresh data on every message
    garmin_summary, intervals_summary = get_coaching_context()

    # Get coaching response
    reply = chat_with_coach(incoming_msg, from_number, garmin_summary, intervals_summary)

    print(f"Coach reply: {reply}")

    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)

@app.route("/health", methods=["GET"])
def health():
    return "Coach is alive!", 200

if __name__ == "__main__":
    print("🏊 Triathlon Coach WhatsApp Server starting...")
    print("Make sure ngrok is running: ngrok http 5000")
    app.run(debug=True, port=5000)