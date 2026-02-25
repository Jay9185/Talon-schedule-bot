import os
import sys
import json
import requests
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
        
        # Expanded system tooltip filter
        ignore_list = [
            "Activity Type", 
            "Click here", 
            "Take Academic Attendance",
            "Activity Completion",
            "Edit",
            "Authorize Acvtivty",
            "Ops Check In",
            "Delete",
            "View",
            "Report",
            "Grade",
            "Cancel"
        ]
        
        for tag in all_elements:
            title_text = tag.get('title', '').strip()
            if not title_text: continue
                
            # 1. THE SNIPER: If it officially says "Comments:", this is 100% a dispatcher remark.
            if "Comments:" in title_text:
                remark = title_text.split("Comments:")[-1].strip()
                break # We found the exact remark, stop looking immediately.
                
            # 2. THE FILTER: Check if this tooltip is a known system button
            is_system_button = any(title_text.lower().startswith(ignore.lower()) for ignore in ignore_list)
            
            # 3. THE FALLBACK: If it's not a system button, save it just in case
            if not is_system_button and len(title_text) > 3:
                valid_fallback_titles.append(title_text)
                
        # 4. THE HEURISTIC: If we didn't find "Comments:" but found other valid tooltips, 
        # assume the longest text is the human-typed remark (since system buttons are short).
        if not remark and valid_fallback_titles:
            remark = max(valid_fallback_titles, key=len)
        # ----------------------------------
            
        start_parts = start.split(" ")
        stop_parts = stop.split(" ")
        
        if len(start_parts) >= 3 and len(stop_parts) >= 3:
            date_str = f"{start_parts[0]} {start_parts[1]}"
            time_str = f"{start_parts[2]} - {stop_parts[2]}"
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

def compare_schedules(old_sched, new_sched):
    new_alerts = []
    updated_alerts = []
    deleted_alerts = []
    
    old_dict = {f"{f['date']}_{f['time']}": f for f in old_sched}
    new_dict = {f"{f['date']}_{f['time']}": f for f in new_sched}
    new_dates = set([f['date'] for f in new_sched])

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
            
            # Check if dispatch added or changed a remark
            old_remark = old_f.get('remark', '')
            if old_remark != f['remark']: 
                if f['remark']:
                    changes.append(f"MOD: Remark updated to '{f['remark']}'")
                else:
                    changes.append(f"MOD: Remark removed")

            if changes:
                f['changes_text'] = "\n".join(changes)
                updated_alerts.append(f)

    for key, old_f in old_dict.items():
        if key not in new_dict and old_f['date'] in new_dates:
            deleted_alerts.append(old_f)

    return new_alerts, updated_alerts, deleted_alerts

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    try: requests.post(url, json=payload)
    except Exception as e: print(f"Telegram error: {e}")

def update_trmnl(flights, timestamp_str):
    webhook = os.environ.get("TRMNL_WEBHOOK_URL")
    if not webhook: return
    payload = {"merge_variables": {"flights": flights[:4], "updated_at": timestamp_str}}
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
                    msg += f"<b>Lesson:</b> {f['lesson']} ({f['type']})\n"
                    msg += f"<b>Instructor:</b> {f['ip']}\n"
                    msg += f"<b>Reserved:</b> {f['res']}\n"
                    if alert_type != "DELETED":
                        msg += f"<b>Status:</b> {f['status']}\n"
                    
                    if f.get('remark'):
                        msg += f"<b>Remark:</b> {f['remark']}\n"
                    
                    if alert_type == "UPDATED":
                        msg += f"<i>{f['changes_text']}</i>\n"
                    msg += "</blockquote>\n"
            
            msg += f"<code>Last Updated: {now_mst}</code>"

            print("Changes detected! Sending to Telegram...")
            send_telegram(msg)
        else:
            print("No changes detected since last check. Staying silent.")

        print("Sending current snapshot to TRMNL...")
        update_trmnl(current_schedule, now_mst)

        with open(MEMORY_FILE, "w") as f:
            json.dump(current_schedule, f, indent=4)
        print("✅ Run complete. Memory updated.")

if __name__ == "__main__":
    run_scraper()
