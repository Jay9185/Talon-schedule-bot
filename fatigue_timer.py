import os
import json
import requests
from datetime import datetime, timezone, timedelta
import duty_rules
from duty_rules import MAX_DUTY_HOURS, MAX_CONSECUTIVE_DAYS, MIN_REST_HOURS

MEMORY_FILE = "memory.json"

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Exception: {e}")

def generate_report():
    if not os.path.exists(MEMORY_FILE):
        print("No memory.json found. Run the main scraper first.")
        return

    with open(MEMORY_FILE, "r") as f:
        schedule = json.load(f)

    mst_tz = timezone(timedelta(hours=-7))
    now_mst = datetime.now(mst_tz)
    now = now_mst.replace(tzinfo=None)
    today_date = now.date()

    periods = duty_rules.build_duty_periods(schedule, now)
    work_dates = duty_rules.duty_dates(periods)

    # --- 1. CONSECUTIVE WORKING DAYS (limit 8, day off required after) ---
    streak = duty_rules.streak_ending(work_dates, today_date)
    days_left = max(0, MAX_CONSECUTIVE_DAYS - streak)
    last_work_day = today_date + timedelta(days=days_left)
    rest_date = last_work_day + timedelta(days=1)

    # --- 2. DUTY PERIODS TODAY (starting today, or still running from yesterday) ---
    todays = [p for p in periods
              if p['start'].date() == today_date or p['start'] <= now < p['end']]

    if todays:
        duty_str = "\n".join(
            f"{p['hours']:.1f} / {MAX_DUTY_HOURS:.1f} Hrs "
            f"({p['start'].strftime('%d %b %H:%M')} - {p['end'].strftime('%d %b %H:%M')})"
            for p in todays
        )
    else:
        duty_str = "No working events scheduled today."
    over_limit = any(p['hours'] > MAX_DUTY_HOURS for p in todays)

    # Earliest legal report time after the most recent duty period that has ended/started
    prior = [p for p in periods if p['start'] <= now]
    next_legal = prior[-1]['end'] + timedelta(hours=MIN_REST_HOURS) if prior else None

    # --- 3. BUILD AND SEND TELEGRAM ALERT ---
    msg = "<pre>\n"
    msg += "========================================\n"
    msg += "    AEROGUARD FATIGUE STATUS TIMER      \n"
    msg += "========================================\n"
    msg += f"Time: {now_mst.strftime('%I:%M %p MST')}\n"
    msg += "----------------------------------------\n"
    msg += f"Current Streak: Day {streak} of {MAX_CONSECUTIVE_DAYS}\n"

    if streak == 0:
        msg += "Status:         OFF DUTY TODAY\n"
    else:
        msg += f"Days Remaining: {days_left} Days\n"
        msg += f"Last Work Day:  {last_work_day.strftime('%A, %d %b')}\n"
        msg += f"Day Off Due:    {rest_date.strftime('%A, %d %b')}\n"

    msg += "----------------------------------------\n"
    msg += f"Duty Span (12-hr max from start):\n{duty_str}\n"
    if next_legal and next_legal > now:
        msg += f"Next legal start (12-hr rest): {next_legal.strftime('%d %b %H:%M')}\n"

    if over_limit:
        msg += "\n⚠️ LEGALITY WARNING: 12-Hr Span Exceeded\n"
    if streak > MAX_CONSECUTIVE_DAYS:
        msg += f"\n⚠️ LEGALITY WARNING: {MAX_CONSECUTIVE_DAYS}-Day Limit Exceeded - Day Off Required\n"
    elif streak == MAX_CONSECUTIVE_DAYS:
        msg += "\n⚠️ LEGALITY WARNING: Mandatory Day Off Tomorrow\n"

    msg += "========================================\n"
    msg += "</pre>"

    send_telegram(msg)
    print("Fatigue report sent!")

if __name__ == "__main__":
    generate_report()
