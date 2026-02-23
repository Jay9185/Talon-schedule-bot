import os
import sys
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
# Using the exact AeroGuard routing ID link
TALON_LOGIN_URL = "https://apps4.talonsystems.com/tseta/servlet/content?module=home&page=homepg&zajael1120=42DC6E6C4E5A723E80D0BF0AC5A1C8AF"

def run_recon():
    username = os.environ.get("TALON_USER")
    password = os.environ.get("TALON_PASS")
    
    if not username or not password:
        print("🚨 Missing Talon credentials in GitHub Secrets!")
        sys.exit(1)

    print("🚀 Launching Headless Browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        print(f"🌐 Navigating to {TALON_LOGIN_URL}")
        try:
            page.goto(TALON_LOGIN_URL, timeout=15000)
            
            # Wait to allow any redirects to the login screen to finish
            page.wait_for_timeout(3000)

            # --- LOGIN SEQUENCE ---
            print("🔐 Attempting to log in...")
            
            # Fill the standard Talon login fields
            page.fill("input[name='userid']", username, timeout=5000)
            page.fill("input[name='password']", password, timeout=5000)
            page.click("input[type='submit'], button[type='submit']", timeout=5000)
            
            print("⏳ Waiting for dashboard to load...")
            # Give the dashboard plenty of time to populate after clicking submit
            page.wait_for_timeout(8000) 

        except Exception as e:
            print(f"⚠️ Encountered an issue during navigation or login: {e}")

        # --- CAPTURE DATA ---
        print("📸 Taking screenshot of the current page...")
        page.screenshot(path="talon_dashboard.png", full_page=True)

        print("📄 Dumping HTML structure...")
        with open("talon_source.html", "w", encoding="utf-8") as f:
            f.write(page.content())

        print("✅ Recon complete! Files saved.")
        browser.close()

if __name__ == "__main__":
    run_recon()
