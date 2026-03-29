# ============================================================================
# daily_preview.py — Coach 2.0: Daily 8pm Briefing + Modify Loop
# ============================================================================
#
# REPLACES the existing generate_nightly_message() / nightly_push flow.
#
# HOW IT WORKS:
#   8pm — Railway cron calls POST /nightly (unchanged URL)
#   This module:
#     1. Pulls tomorrow's planned workout from Intervals.icu
#     2. Pulls today's completed activity (Garmin → Intervals.icu)
#     3. Pulls current TSB
#     4. Claude writes a coach-voice briefing
#     5. Sends it to you via WhatsApp
#
#   When you reply:
#     1. Claude classifies your intent:
#        CONFIRM / SWAP / SCALE / SKIP / QUESTION / AMBIGUOUS
#     2. For SWAP/SCALE/SKIP — Claude proposes the change in plain language,
#        waits for your YES before touching Intervals.icu
#     3. For AMBIGUOUS — Claude echoes its interpretation, waits for YES/NO
#     4. For QUESTION — Claude just answers, nothing changes
#     5. For CONFIRM — acknowledges, nothing to push
#
# STATE:
#   Lives in the existing whatsapp_coach.py `conversations` dict.
#   Two new keys added per phone number:
#     "daily_preview"        — the tomorrow workout pulled at 8pm
#     "pending_modification" — a proposed change waiting for athlete YES
#
# ============================================================================

import os
import json
import re
import base64
import requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import anthropic

load_dotenv()

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
    WORKOUT_LIBRARY,
    get_current_phase,
    weeks_to_race,
)

_MONTREAL = ZoneInfo("America/Montreal")


# ─── INTERVALS.ICU HELPERS ───────────────────────────────────────────────────

def _icu_cfg():
    api_key    = os.getenv("INTERVALS_API_KEY")
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    return {
        "base_url":   "https://intervals.icu/api/v1",
        "athlete_id": athlete_id,
        "headers": {
            "Authorization": f"Basic {token}",
            "Content-Type":  "application/json",
        },
    }


def _get_tomorrow_workout():
    """
    Fetch tomorrow's planned workout event from Intervals.icu.
    Returns a dict with name, sport, description, event_id — or None if nothing planned.
    """
    cfg      = _icu_cfg()
    tomorrow = (datetime.now(_MONTREAL).date() + timedelta(days=1)).isoformat()

    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events",
        headers=cfg["headers"],
        params={"oldest": tomorrow, "newest": tomorrow},
        timeout=15,
    )
    r.raise_for_status()
    events = r.json()

    # Find the first WORKOUT event for tomorrow
    for event in events:
        if event.get("category") == "WORKOUT":
            return {
                "event_id":    event.get("id"),
                "name":        event.get("name", ""),
                "sport":       event.get("type", ""),   # Ride / Run / Swim
                "description": event.get("description", ""),
                "date":        tomorrow,
            }
    return None


def _get_today_activity():
    """
    Fetch today's completed activity from Intervals.icu (which syncs from Garmin).
    Returns a compact summary dict, or None if nothing recorded today.
    """
    cfg   = _icu_cfg()
    today = datetime.now(_MONTREAL).date().isoformat()

    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/activities",
        headers=cfg["headers"],
        params={
            "oldest": today,
            "newest": today,
            "fields": "id,type,name,moving_time,distance,icu_training_load,average_heartrate,icu_intensity",
        },
        timeout=15,
    )
    r.raise_for_status()
    acts = r.json()

    if not acts:
        return None

    a = acts[0]
    duration_min = (a.get("moving_time") or 0) // 60
    tss          = round(a.get("icu_training_load") or 0)
    distance_km  = round((a.get("distance") or 0) / 1000, 1)
    avg_hr       = a.get("average_heartrate")

    return {
        "type":        a.get("type", ""),
        "name":        a.get("name", ""),
        "duration":    duration_min,
        "distance_km": distance_km,
        "tss":         tss,
        "avg_hr":      avg_hr,
    }


def _get_current_tsb():
    """
    Fetch the latest TSB from Intervals.icu wellness.
    Returns a float or None.
    """
    cfg     = _icu_cfg()
    today   = datetime.now(_MONTREAL).date().isoformat()
    two_ago = (datetime.now(_MONTREAL).date() - timedelta(days=2)).isoformat()

    r = requests.get(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/wellness",
        headers=cfg["headers"],
        params={"oldest": two_ago, "newest": today},
        timeout=15,
    )
    r.raise_for_status()
    wellness = r.json()

    for w in reversed(wellness):
        if w.get("tsb") is not None:
            return round(w["tsb"], 1)
    return None


def _update_event(event_id, new_name, new_description, sport_type, date_str):
    """
    Replace an existing Intervals.icu event with a new one.
    Intervals.icu has no PATCH for events, so we delete + recreate.
    sport_type: 'Ride' | 'Run' | 'Swim'
    date_str: 'YYYY-MM-DD'
    Returns the new event dict (includes new 'id').
    """
    cfg = _icu_cfg()

    # Delete the old event (ignore 404 — already gone)
    requests.delete(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events/{event_id}",
        headers=cfg["headers"],
        timeout=15,
    )

    # Create a replacement event on the same date
    payload = {
        "name":             new_name,
        "type":             sport_type,
        "category":         "WORKOUT",
        "start_date_local": f"{date_str}T00:00:00",
        "description":      new_description,
    }
    r = requests.post(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events",
        headers=cfg["headers"],
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _delete_event(event_id):
    """
    Delete an event from Intervals.icu (used for SKIP — mark day as rest).
    """
    cfg = _icu_cfg()
    r = requests.delete(
        f"{cfg['base_url']}/athlete/{cfg['athlete_id']}/events/{event_id}",
        headers=cfg["headers"],
        timeout=15,
    )
    return r.status_code in (200, 204, 404)


# ─── WORKOUT LIBRARY LOOKUP ──────────────────────────────────────────────────

def _library_summary_for_sport(sport_type):
    """
    Return a compact list of workouts from the library filtered by sport,
    for injection into the Claude prompt when a SWAP is needed.
    sport_type: 'Ride' | 'Run' | 'Swim'
    """
    sport_map = {"Ride": "bike", "Run": "run", "Swim": "swim"}
    sport_key = sport_map.get(sport_type, "bike")

    lines = []
    for w in WORKOUT_LIBRARY:
        if w["sport"] == sport_key:
            lines.append(
                f"  • {w['name']} | {w['intensity']} | ~{w['duration_min']}min, TSS~{w['est_tss']}"
                f" | {w['description']}"
            )
    return "\n".join(lines) if lines else "(no library workouts for this sport)"


# ─── CLAUDE: BRIEFING GENERATION ─────────────────────────────────────────────

def _generate_briefing(tomorrow_workout, today_activity, tsb):
    """
    Ask Claude to write the 8pm coaching briefing.
    Returns the message text to send to the athlete.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    phase  = get_current_phase()
    wtr    = weeks_to_race()

    # Build today's activity context
    if today_activity:
        today_ctx = (
            f"Today's completed activity: {today_activity['type']} — "
            f"{today_activity['name']}, {today_activity['duration']} min, "
            f"TSS {today_activity['tss']}"
        )
        if today_activity.get("avg_hr"):
            today_ctx += f", avg HR {today_activity['avg_hr']} bpm"
    else:
        today_ctx = "Today's activity: not available (Garmin may not have synced yet)"

    # Build tomorrow's workout context
    if tomorrow_workout:
        tomorrow_ctx = (
            f"Tomorrow's planned workout: {tomorrow_workout['name']} "
            f"({tomorrow_workout['sport']})\n"
            f"Description: {tomorrow_workout['description']}"
        )
    else:
        tomorrow_ctx = "Tomorrow's planned workout: none scheduled"

    tomorrow_date = (datetime.now(_MONTREAL).date() + timedelta(days=1)).strftime("%A %B %d")

    system = f"""You are {ATHLETE_NAME}'s triathlon coach. Write his evening briefing message.

ATHLETE:
  FTP: {FTP_WATTS}W | Bike/Run LTHR: {BIKE_LTHR}/{RUN_LTHR} bpm | Max HR: {MAX_HR}
  Swim threshold: {SWIM_THRESHOLD_PACE}
  Run coaching: pace is primary, HR is confirmatory (lags 60–90 sec)
  Current phase: {phase['phase']} | Weeks to {RACE_NAME}: {wtr}
  Current TSB: {tsb if tsb is not None else 'unknown'}

VOICE: Knowledgeable, warm, direct. Coach to athlete — not a bot report.
No emojis. Keep it under 150 words total. WhatsApp, not email.

MESSAGE STRUCTURE:
1. One warm opener that references today if data is available (1 sentence)
2. "Tomorrow: [workout name]"
3. 2–3 sentences: what it is, key targets (power/pace/HR), why it matters now
4. Optional: one line of context (fatigue level, race proximity if relevant)
5. End with exactly: "Reply ✓ to confirm, or tell me if you want to adjust anything."

If tomorrow is unplanned, say:
"Tomorrow is unplanned — reply to tell me what you're thinking or if it's a rest day."
(and skip steps 2–4)"""

    user = f"""{today_ctx}

{tomorrow_ctx}

Date: {tomorrow_date}
TSB: {tsb}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


# ─── CLAUDE: REPLY CLASSIFICATION + RESPONSE ─────────────────────────────────

def _classify_and_respond(athlete_reply, tomorrow_workout, tsb):
    """
    Ask Claude to classify the athlete's reply and generate a response.

    Claude returns a [PREVIEW_ACTION] JSON block + a plain-language message.
    The JSON block contains:
      {
        "intent":              "CONFIRM|SWAP|SCALE|SKIP|QUESTION|AMBIGUOUS",
        "proposed_name":       "workout name" (SWAP/SCALE only, else null),
        "proposed_description":"full workout text" (SWAP/SCALE only, else null),
        "athlete_message":     "what to send to the athlete"
      }

    Returns (intent, proposed_name, proposed_description, athlete_message)
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    phase  = get_current_phase()
    wtr    = weeks_to_race()

    if tomorrow_workout:
        workout_ctx = (
            f"Tomorrow's planned workout: {tomorrow_workout['name']} "
            f"({tomorrow_workout['sport']})\n"
            f"Description: {tomorrow_workout['description']}"
        )
        library_ctx = _library_summary_for_sport(tomorrow_workout.get("sport", "Ride"))
    else:
        workout_ctx = "Tomorrow has no planned workout."
        library_ctx = ""

    system = f"""You are {ATHLETE_NAME}'s triathlon coach handling his evening reply.

CURRENT CONTEXT:
  Phase: {phase['phase']} | Weeks to {RACE_NAME}: {wtr} | TSB: {tsb}
  {workout_ctx}

AVAILABLE WORKOUTS (for SWAP selection):
{library_ctx}

ATHLETE PROFILE:
  FTP: {FTP_WATTS}W | Bike/Run LTHR: {BIKE_LTHR}/{RUN_LTHR} bpm
  Swim threshold: {SWIM_THRESHOLD_PACE}
  Run coaching: pace primary, HR confirmatory

YOUR TASK:
Classify the athlete's reply and generate a response.

INTENT DEFINITIONS:
  CONFIRM  — athlete is happy with tomorrow as planned (e.g. "✓", "ok", "sounds good")
  SWAP     — replace tomorrow with a different workout type or named session
  SCALE    — keep same workout but adjust intensity or duration (e.g. "shorter", "easier")
  SKIP     — mark tomorrow as rest, athlete is tired or something came up
  QUESTION — athlete is asking something, do not modify the plan
  AMBIGUOUS — reply is unclear, need to confirm interpretation before acting

RULES:
- For SWAP: pick the most appropriate specific named workout from the library above.
  Generate its full Intervals.icu description (plain text format with sections and "- " steps).
- For SCALE: keep the same workout name, adjust the description (reduce power targets by ~10%,
  or shorten duration). Explain what you changed.
- For AMBIGUOUS: echo back your interpretation as a yes/no question.
  Example: "Sounds like you want to scale back the intensity — should I reduce power targets
  by ~10% and keep the duration? Reply YES to confirm."
- For SWAP/SCALE/SKIP: your athlete_message must confirm the change in plain language
  BEFORE it is pushed. End with "Reply YES to confirm, or NO to cancel."
- For CONFIRM/QUESTION: just respond naturally. No YES/NO needed.
- Keep athlete_message under 120 words. Coach voice, not bot.

OUTPUT FORMAT — return this block first, then nothing else:
[PREVIEW_ACTION]
{{
  "intent": "<CONFIRM|SWAP|SCALE|SKIP|QUESTION|AMBIGUOUS>",
  "proposed_name": "<workout name or null>",
  "proposed_description": "<full plain text workout or null>",
  "athlete_message": "<message to send to athlete>"
}}
[/PREVIEW_ACTION]"""

    user = f"Athlete reply: {athlete_reply}"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = response.content[0].text.strip()

    # Parse the [PREVIEW_ACTION] block
    match = re.search(r'\[PREVIEW_ACTION\](.*?)\[/PREVIEW_ACTION\]', raw, re.DOTALL)
    if not match:
        # Claude didn't follow format — treat as QUESTION, return raw text
        return "QUESTION", None, None, raw

    try:
        data = json.loads(match.group(1).strip())
        return (
            data.get("intent", "QUESTION"),
            data.get("proposed_name"),
            data.get("proposed_description"),
            data.get("athlete_message", raw),
        )
    except json.JSONDecodeError:
        return "QUESTION", None, None, raw


# ─── MAIN: 8PM BRIEFING ──────────────────────────────────────────────────────

def run_daily_preview(conversations, athlete_phone):
    """
    Called at 8pm. Pulls data, generates briefing, sends WhatsApp.
    Stores the tomorrow workout in conversations state for the reply loop.

    conversations: the shared dict from whatsapp_coach.py
    athlete_phone: the athlete's WhatsApp number string

    Returns the message text sent (or raises on hard failure).
    """
    print("\n=== Daily Preview: 8pm briefing ===")

    # ── Pull tomorrow's workout ───────────────────────────────────────────────
    tomorrow_workout = None
    try:
        tomorrow_workout = _get_tomorrow_workout()
        if tomorrow_workout:
            print(f"  Tomorrow: {tomorrow_workout['name']} ({tomorrow_workout['sport']})")
        else:
            print("  Tomorrow: no planned workout found")
    except Exception as e:
        print(f"  Warning: could not fetch tomorrow's workout — {e}")

    # ── Pull today's activity ─────────────────────────────────────────────────
    today_activity = None
    try:
        today_activity = _get_today_activity()
        if today_activity:
            print(f"  Today: {today_activity['type']}, {today_activity['duration']}min, TSS {today_activity['tss']}")
        else:
            print("  Today: no activity recorded")
    except Exception as e:
        print(f"  Warning: could not fetch today's activity — {e}")
        # Non-fatal — proceed without it

    # ── Pull current TSB ─────────────────────────────────────────────────────
    tsb = None
    try:
        tsb = _get_current_tsb()
        print(f"  TSB: {tsb}")
    except Exception as e:
        print(f"  Warning: could not fetch TSB — {e}")

    # ── Generate briefing ─────────────────────────────────────────────────────
    print("  Generating briefing with Claude...")
    message = _generate_briefing(tomorrow_workout, today_activity, tsb)

    # ── Store state for reply loop ────────────────────────────────────────────
    # Ensure the conversation entry exists (whatsapp_coach initialises it, but
    # the nightly push runs outside of a webhook so we guard here too)
    if athlete_phone not in conversations:
        conversations[athlete_phone] = {
            "history": [],
            "pending_workout": None,
            "pending_weekly_plan": None,
            "post_workout_state": None,
            "post_workout_rpe": None,
            "post_workout_activity_id": None,
            "post_workout_activity_type": None,
            "daily_preview": None,
            "pending_modification": None,
        }

    conversations[athlete_phone]["daily_preview"] = tomorrow_workout  # may be None
    conversations[athlete_phone]["pending_modification"] = None        # clear any stale state
    print("  Conversation state updated.")

    return message


# ─── REPLY HANDLER ───────────────────────────────────────────────────────────

def handle_preview_reply(athlete_reply, phone_number, conversations):
    """
    Called from the WhatsApp webhook when the athlete replies to the evening briefing.

    Checks whether:
      (a) There is a pending_modification waiting for YES/NO confirmation, OR
      (b) This is a fresh reply to the briefing

    Returns the reply text to send back.
    """
    conv = conversations.get(phone_number, {})
    msg_lower = athlete_reply.strip().lower()

    # ── Case A: waiting for YES/NO on a proposed modification ────────────────
    pending_mod = conv.get("pending_modification")
    if pending_mod:
        if msg_lower in ("yes", "y", "oui", "confirm", "go", "do it"):
            return _execute_modification(pending_mod, phone_number, conversations)
        elif msg_lower in ("no", "n", "non", "cancel", "nevermind", "never mind", "nope"):
            conversations[phone_number]["pending_modification"] = None
            return "No problem — tomorrow stays as planned."
        else:
            # Treat as a new intent — fall through to classify
            conversations[phone_number]["pending_modification"] = None

    # ── Case B: fresh reply — classify intent ─────────────────────────────────
    tomorrow_workout = conv.get("daily_preview")

    tsb = None
    try:
        tsb = _get_current_tsb()
    except Exception:
        pass

    intent, proposed_name, proposed_description, athlete_message = _classify_and_respond(
        athlete_reply, tomorrow_workout, tsb
    )
    print(f"  Preview reply classified as: {intent}")

    if intent in ("SWAP", "SCALE", "SKIP", "AMBIGUOUS"):
        # Store the proposed modification — don't push yet
        conversations[phone_number]["pending_modification"] = {
            "intent":        intent,
            "proposed_name": proposed_name,
            "proposed_desc": proposed_description,
            "event_id":      tomorrow_workout.get("event_id") if tomorrow_workout else None,
            "sport":         tomorrow_workout.get("sport") if tomorrow_workout else None,
            "date":          tomorrow_workout.get("date") if tomorrow_workout else None,
        }
    else:
        # CONFIRM or QUESTION — nothing to store
        conversations[phone_number]["pending_modification"] = None

    return athlete_message


def _execute_modification(pending_mod, phone_number, conversations):
    """
    Athlete said YES — push the confirmed modification to Intervals.icu.
    Returns confirmation message to send back.
    """
    intent    = pending_mod.get("intent")
    event_id  = pending_mod.get("event_id")
    sport     = pending_mod.get("sport", "")

    # Clear pending state regardless of outcome
    conversations[phone_number]["pending_modification"] = None

    # SKIP — delete the event
    if intent == "SKIP":
        if event_id:
            try:
                _delete_event(event_id)
                conversations[phone_number]["daily_preview"] = None
                return "Done — tomorrow is cleared. Rest up."
            except Exception as e:
                return f"Plan updated in my notes — but Intervals.icu update failed ({e}). Remove it manually if needed."
        else:
            return "Tomorrow was already unplanned — you're good to rest."

    # SWAP or SCALE — replace the event (delete + recreate)
    if intent in ("SWAP", "SCALE"):
        new_name  = pending_mod.get("proposed_name") or "Updated workout"
        new_desc  = pending_mod.get("proposed_desc") or ""
        date_str  = pending_mod.get("date") or (datetime.now(_MONTREAL).date() + timedelta(days=1)).isoformat()

        if event_id:
            try:
                result = _update_event(event_id, new_name, new_desc, sport, date_str)
                # Store the new event_id so further replies can modify it again
                if conversations[phone_number].get("daily_preview"):
                    conversations[phone_number]["daily_preview"]["event_id"] = result.get("id")
                # Update the stored preview so further replies see the new workout
                if conversations[phone_number].get("daily_preview"):
                    conversations[phone_number]["daily_preview"]["name"]        = new_name
                    conversations[phone_number]["daily_preview"]["description"] = new_desc
                return (
                    f"Done — tomorrow updated to '{new_name}'.\n"
                    "It will sync to your Garmin within a few minutes."
                )
            except Exception as e:
                return (
                    f"Intervals.icu update failed ({e}).\n"
                    "Plan is noted here but not pushed — update manually before bed."
                )
        else:
            # No event_id — workout wasn't in Intervals.icu to begin with
            return (
                f"Noted — tomorrow is '{new_name}'.\n"
                "There was no existing event to update in Intervals.icu. "
                "Add it manually if you want it on your Garmin."
            )

    # AMBIGUOUS confirmed — treat as CONFIRM
    return "Perfect — tomorrow stays as planned."
