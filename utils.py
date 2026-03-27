from datetime import datetime, timedelta
import time as _time_module


def get_system_time_block():
    """
    Fetches real current time at moment of call.
    Never cached, never inferred — always reflects actual current moment.
    """
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo('America/Montreal')
    except Exception:
        from datetime import timezone
        # Approximate: EDT (UTC-4) Mar-Nov, EST (UTC-5) Nov-Mar
        from datetime import datetime as _dt, timezone as _tz
        _month = _dt.now(_tz.utc).month
        et = _tz(timedelta(hours=-4 if 3 <= _month <= 11 else -5))

    now = datetime.now(et)  # Real system clock, called fresh every time
    today = now.date()
    tomorrow = today + timedelta(days=1)

    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday', 'Sunday']
    today_name = day_names[today.weekday()]
    tomorrow_name = day_names[tomorrow.weekday()]

    hour = now.hour
    if hour < 12:
        time_of_day = "morning"
    elif hour < 17:
        time_of_day = "afternoon"
    elif hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    days_since_monday = today.weekday()
    week_start = today - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6)
    days_remaining_in_week = 6 - days_since_monday  # days after today

    # Next Monday (never today even if today is Monday)
    days_to_next_monday = (7 - today.weekday()) % 7
    if days_to_next_monday == 0:
        days_to_next_monday = 7
    next_monday = today + timedelta(days=days_to_next_monday)

    return f"""[SYSTEM_TIME — READ THIS FIRST]
unix_timestamp: {int(_time_module.time())}
current_datetime: {now.strftime('%Y-%m-%dT%H:%M:%S')} ET
today_date: {today.isoformat()}
today_name: {today_name}
tomorrow_date: {tomorrow.isoformat()}
tomorrow_name: {tomorrow_name}
time_of_day: {time_of_day}
current_week: {week_start.isoformat()} to {week_end.isoformat()}
next_monday: {next_monday.isoformat()}
days_remaining_in_week: {days_remaining_in_week}
workout_recommendation_is_for: {today_name} {today.strftime('%B %d %Y')}
weekly_plan_starts: {next_monday.strftime('%A %B %d %Y')}
[/SYSTEM_TIME]"""
