from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo('America/Montreal')
except Exception:
    # Fallback for Windows without tzdata package installed
    # Montreal is EDT (UTC-4) Mar-Nov, EST (UTC-5) Nov-Mar
    _now_utc = datetime.now(timezone.utc)
    _month = _now_utc.month
    _ET = timezone(timedelta(hours=-4 if 3 <= _month <= 11 else -5))

def get_system_time_block():
    """Authoritative time context injected at top of every Claude message."""
    et = _ET
    now = datetime.now(et)
    today = now.date()
    tomorrow = today + timedelta(days=1)

    day_names = ['Monday','Tuesday','Wednesday','Thursday',
                 'Friday','Saturday','Sunday']
    today_name = day_names[today.weekday()]
    tomorrow_name = day_names[tomorrow.weekday()]

    days_since_monday = today.weekday()
    week_start = today - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6)
    days_remaining = 7 - days_since_monday - 1

    return f"""[SYSTEM_TIME]
current_datetime: {now.strftime('%Y-%m-%dT%H:%M')} ET
today: {today_name} {today.strftime('%B %d %Y')}
tomorrow: {tomorrow_name} {tomorrow.strftime('%B %d %Y')}
current_week: {week_start.strftime('%b %d')} to {week_end.strftime('%b %d %Y')}
days_remaining_this_week: {days_remaining}
workout_recommendation_target_date: {tomorrow_name} {tomorrow.strftime('%B %d %Y')}
[/SYSTEM_TIME]"""
