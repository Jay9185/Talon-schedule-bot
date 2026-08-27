import os
import json
import requests
from datetime import datetime, timezone, timedelta

MEMORY_FILE = "memory.json"

def is_cancelled(f):
    status = f.get('status', '').lower()
    return 'cancel' in status or 'cnx' in status

def is_rest_period(f):
    return "Rest Period" in f.get('type', '') or "Rest Period" in f.get('lesson', '')

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

    # Filter out cancelled flights for fatigue calculations
    active_events = [f for f in schedule if not is_cancelled(f)]
    
    mst_tz = timezone(timedelta(hours=-7))
    now_mst = datetime.now(mst_tz)
    current_year = now_mst.year
    today_date = now_mst.date()

    def parse_dt(d_str, t_str):
        clean_date = "".join(c for c in d_str if c.isalnum() or c.isspace()).strip()
        dt_str = f"{clean_date} {current_year} {t_str}"
        dt = datetime.strptime(dt_str, "%d %b %Y %H:%M")
        if dt.month == 12 and now_mst.month < 3: dt = dt.replace(year=current_year - 1)
        elif dt.month < 3 and now_mst.month == 12: dt = dt.replace(year=current_year + 1)
        return dt

    # --- 1. CALCULATE CONSECUTIVE DAYS STREAK ---
    # (Only counts days where actual work occurred, ignores pure rest days)
    working_flights = [f for f in active_events if not is_rest_period(f)]
    unique_dates = set()
    for f in working_flights:
        try:
            unique_dates.add(parse_dt(f['date'], "00:00").date())
        except:
            pass

    streak = 0
    if today_date in unique_dates:
        streak = 1
        check_date = today_date - timedelta(days=1)
        while check_date in unique_dates:
            streak += 1
            check_date -= timedelta(days=1)
            
    days_left = max(0, 7 - streak)
    rest_date = today_date + timedelta(days=days_left)

    # --- 2. CALCULATE TODAY'S DUTY HOURS ---
    today_events = [f for f in active_events if parse_dt(f['date'], "00:00").date() == today_date]
    
    # Sort chronologically to apply the circuit breaker in the correct order
    today_events.sort(key=lambda x: parse_dt(x['date'], x['time'].split("-")[0].strip()))
    
    duty_hours = 0.0
    duty_str = "No working events scheduled today."
    
    duty_start = None
    worst_start = None
    worst_end = None
    
    for df in today_events:
        if is_rest_period(df):
            duty_start = None # CIRCUIT BREAKER: Resets duty clock
            continue
            
        parts = df['time'].split("-")
        st = parse_dt(df['date'], parts[0].strip())
        et = parse_dt(df['date'], parts[1].split("(")[0].strip())
        if "(+1D)" in df['time']: et += timedelta(days=1)
        
        if duty_start is None:
            duty_start = st
            
        span = (et - duty_start).total_seconds() / 3600
        if span > duty_hours:
            duty_hours = span
            worst_start = duty_start
            worst_end = et
            
    if worst_start and worst_end:
        duty_str = f"{duty_hours:.1f} / 12.0 Hrs ({worst_start.strftime('%H:%M')} - {worst_end.strftime('%H:%M')})"
    
    # --- 3. BUILD AND SEND TELEGRAM ALERT ---
    msg = "<pre>\n"
    msg += "========================================\n"
    msg += "    AEROGUARD FATIGUE STATUS TIMER      \n"
    msg += "========================================\n"
    msg += f"Time: {now_mst.strftime('%I:%M %p MST')}\n"
    msg += "----------------------------------------\n"
    msg += f"Current Streak: Day {streak} of 7\n"
    
    if streak == 0:
        msg += "Status:         OFF DUTY TODAY\n"
    else:
        msg += f"Days Remaining: {days_left} Days\n"
        msg += f"Hard Rest Day:  {rest_date.strftime('%A, %d %b')}\n"
        
    msg += "----------------------------------------\n"
    msg += f"Today's Duty Span:\n{duty_str}\n"
    
    if duty_hours > 12.0:
        msg += "\n⚠️ LEGALITY WARNING: 12-Hr Span Exceeded\n"
    if streak >= 7:
        msg += "\n⚠️ LEGALITY WARNING: Mandatory Rest Required Tomorrow\n"
        
    msg += "========================================\n"
    msg += "</pre>"

    send_telegram(msg)
    print("Fatigue report sent!")

if __name__ == "__main__":
    generate_report()
