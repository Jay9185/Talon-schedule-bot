import os
import sys
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
TALON_LOGIN_URL = "https://apps4.talonsystems.com/tseta/servlet/content?module=home&page=homepg"

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
        page.goto(TALON_LOGIN_URL)
        
        # Wait a moment to let Talon redirect us to the actual login page
        print("⏳ Waiting for redirect to login screen...")
        page.wait_for_timeout(3000)

        # --- LOGIN SEQUENCE ---
        print("🔐 Attempting to log in...")
        try:
            # Look for standard Talon login fields
            page.fill("input[name='userid']", username, timeout=5000)
            page.fill("input[name='password']", password, timeout=5000)
            page.click("input[type='submit'], button[type='submit']", timeout=5000)
            
            print("⏳ Waiting for dashboard to load...")
            # Give the dashboard plenty of time to load after clicking submit
            page.wait_for_timeout(7000) 
        except Exception as e:
            print(f"⚠️ Could not find standard login fields. Taking snapshot to investigate: {e}")

        # --- CAPTURE DATA ---
        print("📸 Taking screenshot of the current page...")
        page.screenshot(path="talon_dashboard.png")

        print("📄 Dumping HTML structure...")
        with open("talon_source.html", "w", encoding="utf-8") as f:
            f.write(page.content())

        print("✅ Recon complete! Files saved.")
        browser.close()

if __name__ == "__main__":
    run_recon()
