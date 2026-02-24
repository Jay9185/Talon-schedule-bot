import os
import sys
import json
import requests
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
            "type": act_type
        })
    return flights_data

def compare_schedules(old_sched, new_sched):
    """Compares the new schedule against memory to find new or updated flights."""
    new_alerts = []
    updated_alerts = []

    # Use Date + Lesson as a unique identifier to track changes over time
    old_dict = {f"{f['date']}_{f['lesson']}": f for f in old_sched}

    for f in new_sched:
        key = f"{f['date']}_{f['lesson']}"
        if key not in old_dict:
            new_alerts.append(f)
        else:
            # Check if any crucial details changed on this existing lesson
            old_f = old_dict[key]
            changes = []
            if old_f['time'] != f['time']: changes.append(f"⏰ Time: {old_f['time']} ➡️ {f['time']}")
            if old_f['ip'] != f['ip']: changes.append(f"👨‍✈️ IP: {old_f['ip']} ➡️ {f['ip']}")
            if old_f['res'] != f['res']: changes.append(f"🏢 Res: {old_f['res']} ➡️ {f['res']}")
            if old_f['status'] != f['status']: changes.append(f"✅ Stat: {old_f['status']} ➡️ {f['status']}")

            if changes:
                f['changes_text'] = "\n".join(changes)
                updated_alerts.append(f)

    return new_alerts, updated_alerts

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try: requests.post(url, json=payload)
    except Exception as e: print(f"Telegram error: {e}")

def update_trmnl(flights):
    webhook = os.environ.get("TRMNL_WEBHOOK_URL")
    if not webhook: return
    payload = {"merge_variables": {"flights": flights[:4]}}
    try: requests.post(webhook, json=payload)
    except Exception as e: print(f"TRMNL error: {e}")

def run_scraper():
    username = os.environ.get("TALON_USER")
    password = os.environ.get("TALON_PASS")
    
    # 1. Load memory
    old_schedule = []
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                old_schedule = json.load(f)
        except Exception:
            pass

    # 2. Scrape Talon
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

    # 3. Process, Compare, and Alert
    if html_dump:
        current_schedule = extract_schedule(html_dump)
        if not current_schedule:
            print("No events found in Talon.")
            return

        new_flights, updated_flights = compare_schedules(old_schedule, current_schedule)

        # Build Telegram Message ONLY if there are changes
        if new_flights or updated_flights:
            msg = "🦅 <b>AeroGuard Talon Update</b>\n\n"
            
            if new_flights:
                msg += "🆕 <b>NEWLY SCHEDULED:</b>\n"
                for f in new_flights:
                    msg += f"📅 <b>{f['date']}</b> | {f['time']}\n"
                    msg += f"✈️ {f['lesson']} ({f['type']})\n"
                    msg += f"👨‍✈️ {f['ip']} | 🏢 {f['res']}\n\n"
            
            if updated_flights:
                msg += "🔄 <b>UPDATED DETAILS:</b>\n"
                for f in updated_flights:
                    msg += f"📅 <b>{f['date']} - {f['lesson']}</b>\n"
                    msg += f"{f['changes_text']}\n\n"

            print("Changes detected! Sending to Telegram...")
            send_telegram(msg)
        else:
            print("No changes detected since last check. Staying silent.")

        # Always update the TRMNL screen with the latest view
        print("Sending current snapshot to TRMNL...")
        update_trmnl(current_schedule)

        # 4. Save new memory
        with open(MEMORY_FILE, "w") as f:
            json.dump(current_schedule, f, indent=4)
        print("✅ Run complete. Memory updated.")

if __name__ == "__main__":
    run_scraper()
