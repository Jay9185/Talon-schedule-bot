import os
import json
import requests
from datetime import datetime, timezone, timedelta

MEMORY_FILE = "memory.json"

def is_cancelled(f):
    """Returns True if the flight is marked as cancelled or CNX."""
    status = f.get('status', '').lower()
    return 'cancel' in status or 'cnx' in status

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
    active_flights = [f for f in schedule if not is_cancelled(f)]
    
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
    unique_dates = set()
    for f in active_flights:
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
    today_flights = [f for f in active_flights if parse_dt(f['date'], "00:00").date() == today_date]
    
    duty_hours = 0.0
    duty_str = "No events scheduled today."
    
    if today_flights:
        start_times = []
        end_times = []
        for df in today_flights:
            parts = df['time'].split("-")
            st = parts[0].strip()
            et = parts[1].split("(")[0].strip()
            
            s_dt = parse_dt(df['date'], st)
            e_dt = parse_dt(df['date'], et)
            if "(+1D)" in df['time']: e_dt += timedelta(days=1)
            
            start_times.append(s_dt)
            end_times.append(e_dt)
            
        duty_start = min(start_times)
        duty_end = max(end_times)
        duty_hours = (duty_end - duty_start).total_seconds() / 3600
        duty_str = f"{duty_hours:.1f} / 12.0 Hrs ({duty_start.strftime('%H:%M')} - {duty_end.strftime('%H:%M')})"
    
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
