import os
import sys
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
TALON_LOGIN_URL = "https://apps4.talonsystems.com/tseta/servlet/content?module=home&page=homepg&zajael1120=42DC6E6C4E5A723E80D0BF0AC5A1C8AF"

def extract_schedule(html_content):
    print("\n🔍 Parsing Talon schedule...")
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find the main schedule table
    table = soup.find('table', id='tblSchedListS')
    if not table:
        print("❌ Could not find the schedule table in the HTML.")
        return []

    # Get all rows in the table body
    tbody = table.find('tbody')
    if not tbody:
        return []
        
    rows = tbody.find_all('tr', recursive=False)
    flights_data = []

    for row in rows:
        cols = row.find_all('td', recursive=False)
        if len(cols) < 10:
            continue
            
        start = cols[1].get_text(strip=True)
        stop = cols[2].get_text(strip=True)
        status = cols[3].get_text(strip=True)
        act_type = cols[4].get_text(strip=True)
        resource = cols[5].get_text(strip=True)
        unit = cols[7].get_text(strip=True)
        instructor = cols[8].get_text(strip=True)

        # Skip rest periods, we only want actionable events
        if "Rest Period" in act_type:
            continue
            
        # Format the date and time strings
        start_parts = start.split(" ")
        stop_parts = stop.split(" ")
        
        if len(start_parts) >= 3 and len(stop_parts) >= 3:
            date_str = f"{start_parts[0]} {start_parts[1]}"
            time_str = f"{start_parts[2]} - {stop_parts[2]}"
            if start_parts[0] != stop_parts[0]: # Crosses midnight
                time_str += " (+1D)"
        else:
            date_str = start
            time_str = stop

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

def run_scraper():
    username = os.environ.get("TALON_USER")
    password = os.environ.get("TALON_PASS")
    
    if not username or not password:
        print("🚨 Missing Talon credentials in GitHub Secrets!")
        sys.exit(1)

    print("🚀 Launching Headless Browser...")
    html_dump = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        try:
            print(f"🌐 Navigating to login...")
            page.goto(TALON_LOGIN_URL, timeout=15000)
            page.wait_for_timeout(3000)

            print("🔐 Logging in...")
            page.fill("input[name='uname']", username, timeout=5000)
            page.locator("input[name='password']").click() 
            page.wait_for_timeout(500) 
            page.fill("input[name='password']", password, timeout=5000, force=True) 
            page.click("input[id='butlogin']", timeout=5000)
            
            print("⏳ Waiting for dashboard to load...")
            page.wait_for_timeout(8000) 
            
            # Grab the HTML content instead of saving it to a file
            html_dump = page.content()

        except Exception as e:
            print(f"⚠️ Encountered an issue: {e}")
            browser.close()
            sys.exit(1)

        browser.close()

    # --- PROCESS THE DATA ---
    if html_dump:
        schedule = extract_schedule(html_dump)
        
        print("\n" + "="*45)
        if not schedule:
            print(f"  No upcoming events found in Talon.")
        else:
            for f in schedule:
                print(f"📅 DATE: {f['date']}")
                print(f"⏰ TIME: {f['time']}")
                print(f"✈️  MSN:  {f['lesson']} ({f['type']})")
                print(f"👨‍✈️ IP:   {f['ip']}")
                print(f"🏢 RES:  {f['res']}")
                print(f"✅ STAT: {f['status']}")
                print("-" * 45)

if __name__ == "__main__":
    run_scraper()
