from datetime import datetime, timedelta
import time as time_module


def _get_tz():
    """Return Eastern timezone, with fallback to UTC if tzdata unavailable."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('America/Toronto')
    except Exception:
        import datetime as _dt
        return _dt.timezone.utc


def get_system_time_block():
    """
    Called fresh on every single request — never cached.
    Pre-computes all date strings so Claude never calculates dates.
    """
    et = _get_tz()
    now = datetime.now(et)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday', 'Sunday']

    today_name = day_names[today.weekday()]
    tomorrow_name = day_names[tomorrow.weekday()]
    day_after_name = day_names[day_after.weekday()]

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

    days_to_next_monday = (7 - today.weekday()) % 7
    if days_to_next_monday == 0:
        days_to_next_monday = 7
    next_monday = today + timedelta(days=days_to_next_monday)

    # Pre-format everything — Claude reads finished strings only
    today_full = f"{today_name} {today.strftime('%B %d %Y')}"
    tomorrow_full = f"{tomorrow_name} {tomorrow.strftime('%B %d %Y')}"
    day_after_full = f"{day_after_name} {day_after.strftime('%B %d %Y')}"

    return f"""[SYSTEM_TIME]
unix_timestamp: {int(time_module.time())}
NOW: {now.strftime('%Y-%m-%dT%H:%M:%S')} Montreal time
TODAY IS: {today_full}
TOMORROW IS: {tomorrow_full}
DAY AFTER TOMORROW IS: {day_after_full}
time_of_day: {time_of_day}
current_week: {week_start.strftime('%b %d')} to {week_end.strftime('%b %d %Y')}
next_monday: {next_monday.strftime('%A %B %d %Y')}
WORKOUT RECOMMENDATION MUST BE FOR: {tomorrow_full}
WEEKLY PLAN STARTS ON: {next_monday.strftime('%A %B %d %Y')}
[/SYSTEM_TIME]"""
