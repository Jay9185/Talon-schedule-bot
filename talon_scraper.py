import os
import sys
import json
import requests
import html
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
TALON_LOGIN_URL = "https://apps4.talonsystems.com/tseta/servlet/content?module=home&page=homepg&zajael1120=42DC6E6C4E5A723E80D0BF0AC5A1C8AF"
MEMORY_FILE = "memory.json"

def extract_schedule(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    table = soup.find('table', id='tblSchedListS')
    if not table: return []

    tbody = table.find('tbody')
    if not tbody: return []
        
    rows = tbody.find_all('tr', recursive=False)
    flights_data = []

    for row in rows:
        cols = row.find_all('td', recursive=False)
        if len(cols) < 10: continue
            
        start = cols[1].get_text(strip=True)
        stop = cols[2].get_text(strip=True)
        status = cols[3].get_text(strip=True)
        act_type = cols[4].get_text(strip=True)
        resource = cols[5].get_text(strip=True)
        unit = cols[7].get_text(strip=True)
        instructor = cols[8].get_text(strip=True)

        if "Rest Period" in act_type: continue

        # --- BULLETPROOF REMARK SCANNER ---
        remark = ""
        all_elements = [row] + row.find_all(True) 
        valid_fallback_titles = []
        
        ignore_list = [
            "Activity Type", "Click here", "Take Academic Attendance",
            "Activity Completion", "Edit", "Authorize Activity",
            "Ops Check In", "Delete", "View", "Report", "Grade", "Cancel"
        ]
        
        for tag in all_elements:
            title_text = tag.get('title', '').strip()
            if not title_text: continue
                
            if "Comments:" in title_text:
                remark = title_text.split("Comments:")[-1].strip()
                break 
                
            is_system_button = any(title_text.lower().startswith(ignore.lower()) for ignore in ignore_list)
            
            if not is_system_button and len(title_text) > 3:
                valid_fallback_titles.append(title_text)
                
        if not remark and valid_fallback_titles:
            remark = max(valid_fallback_titles, key=len)
        # ----------------------------------
            
        start_parts = start.split()
        stop_parts = stop.split()
        
        if len(start_parts) >= 3 and len(stop_parts) >= 3:
            date_str = f"{start_parts[0]} {start_parts[1]}"
            time_str = f"{start_parts[-1]} - {stop_parts[-1]}"
            if start_parts[0] != stop_parts[0]: time_str += " (+1D)"
        else:
            date_str, time_str = start, stop

        flights_data.append({
            "date": date_str,
            "time": time_str,
            "status": status,
            "ip": instructor if instructor else "TBD",
            "res": resource if resource else "TBD",
            "lesson": unit[:20] if unit else "Unknown", 
            "type": act_type,
            "remark": remark
        })
    return flights_data

def filter_old_flights(schedule):
    """Keeps future flights and recent flights up to 2 days old. Scrubs dirty Talon dates."""
    mst_tz = timezone(timedelta(hours=-7))
    now = datetime.now(mst_tz)
    cutoff_date = (now - timedelta(days=2)).date()
    current_year = now.year
    filtered_schedule = []
    
    for f in schedule:
        try:
            # Strip out asterisks or weird hidden HTML characters from stuck classes
            clean_date = "".join(c for c in f['date'] if c.isalnum() or c.isspace()).strip()
            dt_str = f"{clean_date} {current_year}"
            flight_dt = datetime.strptime(dt_str, "%d %b %Y").date()
            
            if flight_dt.month == 12 and now.month < 3:
                flight_dt = flight_dt.replace(year=current_year - 1)
            elif flight_dt.month < 3 and now.month == 12:
                flight_dt = flight_dt.replace(year=current_year + 1)
                
            if flight_dt >= cutoff_date:
                filtered_schedule.append(f)
        except Exception:
            filtered_schedule.append(f)
            
    return filtered_schedule

def is_future_flight(f):
    """Checks if a flight's start time is currently in the future."""
    mst_tz = timezone(timedelta(hours=-7))
    now = datetime.now(mst_tz)
    current_year = now.year
    try:
        start_time_str = f['time'].split("-")[0].strip()
        clean_date = "".join(c for c in f['date'] if c.isalnum() or c.isspace()).strip()
        dt_str = f"{clean_date} {current_year} {start_time_str}"
        flight_dt = datetime.strptime(dt_str, "%d %b %Y %H:%M").replace(tzinfo=mst_tz)
        
        if flight_dt.month == 12 and now.month < 3:
            flight_dt = flight_dt.replace(year=current_year - 1)
        elif flight_dt.month < 3 and now.month == 12:
            flight_dt = flight_dt.replace(year=current_year + 1)
            
        return flight_dt > now
    except:
        return True 

def get_trmnl_flights(schedule):
    """STRICT TRMNL FILTER: Only returns flights where the end time is in the future."""
    mst_tz = timezone(timedelta(hours=-7))
    now = datetime.now(mst_tz)
    current_year = now.year
    trmnl_flights = []
    
    for f in schedule:
        try:
            time_parts = f['time'].split("-")
            if len(time_parts) < 2:
                trmnl_flights.append(f)
                continue
                
            stop_time_str = time_parts[1].split("(")[0].strip()
            clean_date = "".join(c for c in f['date'] if c.isalnum() or c.isspace()).strip()
            
            dt_str = f"{clean_date} {current_year} {stop_time_str}"
            stop_dt = datetime.strptime(dt_str, "%d %b %Y %H:%M").replace(tzinfo=mst_tz)
            
            if "(+1D)" in f['time']:
                stop_dt += timedelta(days=1)
                
            if stop_dt.month == 12 and now.month < 3:
                stop_dt = stop_dt.replace(year=current_year - 1)
            elif stop_dt.month < 3 and now.month == 12:
                stop_dt = stop_dt.replace(year=current_year + 1)
                
            # If the block has passed, ban it from TRMNL
            if stop_dt > now:
                trmnl_flights.append(f)
        except Exception:
            # Drop un-parseable corrupt dates from TRMNL so they don't block the screen
            pass
            
    return trmnl_flights[:4]

def compare_schedules(old_sched, new_sched):
    new_alerts = []
    updated_alerts = []
    deleted_alerts = []
    
    old_dict = {f"{f['date']}_{f['time']}": f for f in old_sched}
    new_dict = {f"{f['date']}_{f['time']}": f for f in new_sched}

    for key, f in new_dict.items():
        if key not in old_dict:
            new_alerts.append(f)
        else:
            old_f = old_dict[key]
            changes = []
            if old_f['lesson'] != f['lesson']: changes.append(f"MOD: Lesson changed: {old_f['lesson']} to {f['lesson']}")
            if old_f['ip'] != f['ip']: changes.append(f"MOD: Instructor changed: {old_f['ip']} to {f['ip']}")
            if old_f['res'] != f['res']: changes.append(f"MOD: Reserved changed: {old_f['res']} to {f['res']}")
            if old_f['status'] != f['status']: changes.append(f"MOD: Status changed: {old_f['status']} to {f['status']}")
            
            old_remark = old_f.get('remark', '')
            if old_remark != f['remark']: 
                if f['remark']: changes.append(f"MOD: Remark updated to '{f['remark']}'")
                else: changes.append(f"MOD: Remark removed")

            if changes:
                f['changes_text'] = "\n".join(changes)
                updated_alerts.append(f)

    for key, old_f in old_dict.items():
        if key not in new_dict:
            if is_future_flight(old_f):
                deleted_alerts.append(old_f)

    return new_alerts, updated_alerts, deleted_alerts

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    try: 
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram API Error: {response.text}")
    except Exception as e: 
        print(f"Telegram Exception: {e}")

def update_trmnl(flights, timestamp_str):
    webhook = os.environ.get("TRMNL_WEBHOOK_URL")
    if not webhook: return
    payload = {"merge_variables": {"flights": flights, "updated_at": timestamp_str}}
    try: requests.post(webhook, json=payload)
    except Exception as e: print(f"TRMNL error: {e}")

def run_scraper():
    username = os.environ.get("TALON_USER")
    password = os.environ.get("TALON_PASS")
    
    mst_tz = timezone(timedelta(hours=-7))
    now_mst = datetime.now(mst_tz).strftime("%d %b %H:%M MST").upper()

    old_schedule = []
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                old_schedule = json.load(f)
        except Exception:
            pass

    print("🚀 Launching Headless Browser...")
    html_dump = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        try:
            page.goto(TALON_LOGIN_URL, timeout=15000)
            page.wait_for_timeout(3000)
            page.fill("input[name='uname']", username, timeout=5000)
            page.locator("input[name='password']").click() 
            page.wait_for_timeout(500) 
            page.fill("input[name='password']", password, timeout=5000, force=True) 
            page.click("input[id='butlogin']", timeout=5000)
            page.wait_for_timeout(8000) 
            html_dump = page.content()
        except Exception as e:
            print(f"⚠️ Encountered an issue: {e}")
        finally:
            browser.close()

    if html_dump:
        current_schedule = extract_schedule(html_dump)
        if not current_schedule:
            print("No events found in Talon.")
            return

        current_schedule = filter_old_flights(current_schedule)
        old_schedule = filter_old_flights(old_schedule)

        new_flights, updated_flights, deleted_flights = compare_schedules(old_schedule, current_schedule)

        if new_flights or updated_flights or deleted_flights:
            alerts_by_date = {}
            for f in new_flights:
                d = f['date']; alerts_by_date.setdefault(d, []).append((f, "NEW"))
            for f in updated_flights:
                d = f['date']; alerts_by_date.setdefault(d, []).append((f, "UPDATED"))
            for f in deleted_flights:
                d = f['date']; alerts_by_date.setdefault(d, []).append((f, "DELETED"))

            msg = "<b>━━ AEROGUARD DISPATCH ━━</b>\n\n"
            
            for date in sorted(alerts_by_date.keys()):
                msg += f"<b>DATE: {date}</b>\n\n"
                
                for f, alert_type in alerts_by_date[date]:
                    if alert_type == "NEW":
                        msg += f"<b>[ NEW ] {f['time']}</b>\n"
                    elif alert_type == "DELETED":
                        msg += f"<b>[ CANCELLED ] <s>{f['time']}</s></b>\n"
                    else:
                        msg += f"<b>[ UPDATE ] {f['time']}</b>\n"
                    
                    msg += "<blockquote>"
                    msg += f"<b>Lesson:</b> {html.escape(f['lesson'])} ({html.escape(f['type'])})\n"
                    msg += f"<b>Instructor:</b> {html.escape(f['ip'])}\n"
                    msg += f"<b>Reserved:</b> {html.escape(f['res'])}\n"
                    if alert_type != "DELETED":
                        msg += f"<b>Status:</b> {html.escape(f['status'])}\n"
                    
                    if f.get('remark'):
                        msg += f"<b>Remark:</b> {html.escape(f['remark'])}\n"
                    
                    if alert_type == "UPDATED":
                        msg += f"<i>{html.escape(f['changes_text'])}</i>\n"
                    msg += "</blockquote>\n"
            
            msg += f"<code>Last Updated: {now_mst}</code>"

            print("Changes detected! Sending to Telegram...")
            send_telegram(msg)
        else:
            print("No changes detected since last check. Staying silent.")

        # Push ONLY active/future flights to TRMNL
        trmnl_payload = get_trmnl_flights(current_schedule)
        print("Sending active/upcoming snapshot to TRMNL...")
        update_trmnl(trmnl_payload, now_mst)

        with open(MEMORY_FILE, "w") as f:
            json.dump(current_schedule, f, indent=4)
        print("✅ Run complete. Memory updated.")

if __name__ == "__main__":
    run_scraper()
