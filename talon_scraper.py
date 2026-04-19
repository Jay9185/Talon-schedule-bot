import os
import sys
import json
import requests
import html
import math
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
    mst_tz = timezone(timedelta(hours=-7))
    now = datetime.now(mst_tz)
    cutoff_date = (now - timedelta(days=2)).date()
    current_year = now.year
    filtered_schedule = []
    
    for f in schedule:
        try:
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
                
            if stop_dt > now:
                trmnl_flights.append(f)
        except Exception:
            pass
            
    return trmnl_flights[:4]

def compare_schedules(old_sched, new_sched):
    new_alerts = []
    updated_alerts = []
    deleted_alerts = []
    
    old_dict = {f"{f['date']}_{f['time']}": f for f in old_sched}
    new_dict = {f"{f['date']}_{f['time']}": f for f in new_sched}

    for f in new_sched:
        key = f"{f['date']}_{f['time']}"
        if key in old_dict:
            f['dispatch_sent'] = old_dict[key].get('dispatch_sent', False)

    for key, f in new_dict.items():
        if key not in old_dict:
            new_alerts.append(f)
        else:
            old_f = old_dict[key]
            changes = []
            if old_f['lesson'] != f['lesson']: changes.append(f"LSN: {old_f['lesson']} -> {f['lesson']}")
            if old_f['ip'] != f['ip']: changes.append(f"PIC: {old_f['ip']} -> {f['ip']}")
            if old_f['res'] != f['res']: changes.append(f"ACF: {old_f['res']} -> {f['res']}")
            if old_f['status'] != f['status']: changes.append(f"STS: {old_f['status']} -> {f['status']}")
            
            old_remark = old_f.get('remark', '')
            if old_remark != f['remark']: 
                if f['remark']: changes.append(f"RMK: '{f['remark']}'")
                else: changes.append(f"RMK REMOVED")

            if changes:
                f['changes_text'] = "\n".join([f"> {c.upper()}" for c in changes])
                updated_alerts.append(f)

    for key, old_f in old_dict.items():
        if key not in new_dict:
            if is_future_flight(old_f):
                deleted_alerts.append(old_f)

    return new_alerts, updated_alerts, deleted_alerts

def evaluate_weather(start_dt, end_dt):
    runway_heading = 70 
    max_wind_limit = 10
    max_crosswind_limit = 6  # Enforcing the 6 KT limit
    
    reasons = []
    is_go = True
    current_wind = "N/A"
    forecast_wind = "N/A"
    max_crosswind_encountered = 0

    def run_limits_math(wind_dir, wind_speed, wind_gust, source_name):
        nonlocal is_go, max_crosswind_encountered
        
        wind_speed = wind_speed or 0
        wind_gust = wind_gust or 0
        max_speed = max(wind_speed, wind_gust)
        
        if max_speed > max_wind_limit:
            is_go = False
            reasons.append(f"[{source_name}] WIND LMT EXCEED {max_speed}KT")

        crosswind = 0
        if wind_dir == "VRB":
            crosswind = max_speed
            if crosswind > max_crosswind_limit:
                is_go = False
                reasons.append(f"[{source_name}] VRB XWC EXCEED {crosswind}KT")
        elif wind_dir is not None:
            angle_diff_radians = math.radians(wind_dir - runway_heading)
            crosswind = round(abs(max_speed * math.sin(angle_diff_radians)), 1)
            max_crosswind_encountered = max(max_crosswind_encountered, crosswind)
            
            if crosswind > max_crosswind_limit:
                is_go = False
                reasons.append(f"[{source_name}] XWC LMT EXCEED {crosswind:04.1f}KT")
                
        dir_str = "VRB" if wind_dir == "VRB" else str(wind_dir).zfill(3) if wind_dir else "000"
        return f"{dir_str}@{wind_speed}" + (f"G{wind_gust}" if wind_gust else "")

    def parse_api_time(t_val):
        if isinstance(t_val, int):
            return datetime.fromtimestamp(t_val, tz=timezone.utc)
        return datetime.fromisoformat(str(t_val).replace('Z', '+00:00'))

    try:
        metar_resp = requests.get("https://aviationweather.gov/api/data/metar?ids=KDVT&format=json", timeout=10)
        if metar_resp.status_code == 200 and metar_resp.json():
            m = metar_resp.json()[0]
            current_wind = run_limits_math(m.get("wdir"), m.get("wspd"), m.get("wgst"), "METAR")

        if start_dt and end_dt:
            start_utc = start_dt.astimezone(timezone.utc)
            end_utc = end_dt.astimezone(timezone.utc)
            taf_resp = requests.get("https://aviationweather.gov/api/data/taf?ids=KDVT&format=json", timeout=10)
            
            if taf_resp.status_code == 200 and taf_resp.json():
                try:
                    overlapping_fcsts = []
                    for fcst in taf_resp.json()[0].get("fcsts", []):
                        time_from = parse_api_time(fcst.get("timeFrom"))
                        time_to = parse_api_time(fcst.get("timeTo"))
                        
                        if time_to > start_utc and time_from < end_utc:
                            overlapping_fcsts.append(fcst)
                            
                    if overlapping_fcsts:
                        worst_wind_str = "N/A"
                        max_peak_seen = -1
                        
                        for fcst in overlapping_fcsts:
                            spd = fcst.get("wspd", 0) or 0
                            gst = fcst.get("wgst", 0) or 0
                            peak = max(spd, gst)
                            
                            period_start_z = parse_api_time(fcst.get("timeFrom")).strftime('%H%M')
                            wind_str = run_limits_math(
                                fcst.get("wdir"), 
                                fcst.get("wspd"), 
                                fcst.get("wgst"), 
                                f"TAF {period_start_z}Z"
                            )
                            
                            if peak > max_peak_seen:
                                max_peak_seen = peak
                                worst_wind_str = wind_str
                                
                        forecast_wind = worst_wind_str
                except Exception as parse_err:
                    print(f"TAF Parse Warning: {parse_err}")

        return {
            "status": "GO" if is_go else "NO-GO",
            "metar_wind": current_wind,
            "taf_wind": forecast_wind,
            "max_crosswind_kt": max_crosswind_encountered,
            "alerts": reasons
        }
    except Exception as e:
        return {"status": "ERROR", "alerts": [f"SYS ERR: {str(e)[:20]}"]}

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Using HTML parse mode to cleanly render the <pre> tag for fixed-width text
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    try: 
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram API Error: {response.text}")
    except Exception as e: 
        print(f"Telegram Exception: {e}")

def update_trmnl(flights, timestamp_str, weather_data):
    webhook = os.environ.get("TRMNL_WEBHOOK_URL")
    if not webhook: return
    
    payload = {
        "merge_variables": {
            "flights": flights, 
            "updated_at": timestamp_str,
            "go_nogo": weather_data.get("status", "N/A"),
            "wind_data": weather_data.get("metar_wind", "N/A"),
            "crosswind": weather_data.get("max_crosswind_kt", 0)
        }
    }
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

    print("Launching Headless Browser...")
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
            print(f"Encountered an issue: {e}")
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

        trmnl_payload = get_trmnl_flights(current_schedule)
        weather_decision = {"status": "NO FLIGHTS", "alerts": []}
        trigger_weather_dispatch = False
        target_flight_details = None
        
        if trmnl_payload:
            next_f = trmnl_payload[0]
            current_year = datetime.now(mst_tz).year
            try:
                time_parts = next_f['time'].split("-")
                start_time_str = time_parts[0].strip()
                end_time_str = time_parts[1].split("(")[0].strip()
                
                clean_date = "".join(c for c in next_f['date'] if c.isalnum() or c.isspace()).strip()
                
                start_dt_str = f"{clean_date} {current_year} {start_time_str}"
                end_dt_str = f"{clean_date} {current_year} {end_time_str}"
                
                start_dt = datetime.strptime(start_dt_str, "%d %b %Y %H:%M").replace(tzinfo=mst_tz)
                end_dt = datetime.strptime(end_dt_str, "%d %b %Y %H:%M").replace(tzinfo=mst_tz)
                
                if "(+1D)" in next_f['time']:
                    end_dt += timedelta(days=1)
                
                if start_dt.month == 12 and datetime.now(mst_tz).month < 3:
                    start_dt = start_dt.replace(year=current_year - 1)
                    end_dt = end_dt.replace(year=current_year - 1)
                elif start_dt.month < 3 and datetime.now(mst_tz).month == 12:
                    start_dt = start_dt.replace(year=current_year + 1)
                    end_dt = end_dt.replace(year=current_year + 1)
                    
                weather_decision = evaluate_weather(start_dt, end_dt)
                
                hours_until_flight = (start_dt - datetime.now(mst_tz)).total_seconds() / 3600
                is_preflight_window = (0 < hours_until_flight <= 3)
                
                target_key = f"{next_f['date']}_{next_f['time']}"
                for f in current_schedule:
                    if f"{f['date']}_{f['time']}" == target_key:
                        f['weather_status'] = weather_decision['status']
                        
                        if is_preflight_window and not f.get('dispatch_sent'):
                            trigger_weather_dispatch = True
                            target_flight_details = f
                            f['dispatch_sent'] = True
                        break
                        
            except Exception as e:
                print(f"Date parsing failed for weather evaluation: {e}")
                weather_decision = evaluate_weather(None, None)
        
        is_manual_run = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        
        if is_manual_run and not (new_flights or updated_flights or deleted_flights):
            if trmnl_payload:
                trigger_weather_dispatch = True
                target_flight_details = trmnl_payload[0]

        # ==========================================
        # ACARS TELETYPE PREFLIGHT BRIEF 
        # ==========================================
        if trigger_weather_dispatch and target_flight_details:
            # Format ACARS variables
            acars_date = datetime.now(mst_tz).strftime("%d%b").upper()
            acars_time = target_flight_details['time'].replace(" ", "").replace(":", "")
            acars_lsn = html.escape(target_flight_details['lesson'].upper())[:10]
            acars_typ = html.escape(target_flight_details['type'].upper())[:10]
            acars_pic = html.escape(target_flight_details['ip'].upper())[:10]
            acars_acf = html.escape(target_flight_details['res'].upper())[:15]
            acars_sts = html.escape(target_flight_details['status'].upper())[:10]
            acars_rmk = html.escape(target_flight_details.get('remark', 'NONE').upper())[:15]
            
            wx_status = weather_decision['status'].upper()
            obs = weather_decision.get('metar_wind', 'N/A')
            fct = weather_decision.get('taf_wind', 'N/A')
            xwc = f"{weather_decision.get('max_crosswind_kt', 0):04.1f} KT"

            msg = "<pre>\n"
            msg += "*** AEROGUARD DISPATCH RELEASE ***\n"
            msg += f"DAT: {acars_date.ljust(10)} BLK: {acars_time}\n"
            msg += f"LSN: {acars_lsn.ljust(10)} TYP: {acars_typ}\n"
            msg += f"PIC: {acars_pic.ljust(10)} ACF: {acars_acf}\n"
            msg += f"STS: {acars_sts.ljust(10)} RMK: {acars_rmk}\n\n"
            
            msg += f"WX CHECK: {wx_status}\n"
            msg += "----------------------------------\n"
            msg += f"OBS: {obs}\n"
            msg += f"FCT: {fct}\n"
            msg += f"XWC: {xwc}\n"
            
            if weather_decision.get("alerts"):
                msg += "\nWARN:\n"
                for alert in weather_decision["alerts"]:
                    msg += f"- {html.escape(alert)}\n"
                    
            msg += "**********************************\n"
            msg += "</pre>"

            print("Sending ACARS Preflight Brief to Telegram...")
            send_telegram(msg)

        # ==========================================
        # ACARS TELETYPE SCHEDULE UPDATE
        # ==========================================
        if new_flights or updated_flights or deleted_flights:
            alerts_by_date = {}
            for f in new_flights:
                d = f['date']; alerts_by_date.setdefault(d, []).append((f, "NEW"))
            for f in updated_flights:
                d = f['date']; alerts_by_date.setdefault(d, []).append((f, "UPDATED"))
            for f in deleted_flights:
                d = f['date']; alerts_by_date.setdefault(d, []).append((f, "DELETED"))

            msg = "<pre>\n"
            msg += "*** AEROGUARD SCHEDULING ALERT ***\n"
            
            for date in sorted(alerts_by_date.keys()):
                acars_date = date.replace(" ", "").upper()
                msg += f"\nDAT: {acars_date}\n"
                msg += "----------------------------------\n"
                
                for f, alert_type in alerts_by_date[date]:
                    acars_blk = f['time'].replace(" ", "").replace(":", "")
                    acars_lsn = html.escape(f['lesson'].upper())[:10]
                    acars_acf = html.escape(f['res'].upper())[:15]
                    acars_pic = html.escape(f['ip'].upper())[:15]
                    
                    if alert_type == "NEW":
                        msg += f"ADD: {acars_blk}\n"
                    elif alert_type == "DELETED":
                        msg += f"CNL: {acars_blk}\n"
                    else:
                        msg += f"MOD: {acars_blk}\n"
                        
                    msg += f"LSN: {acars_lsn.ljust(10)} ACF: {acars_acf}\n"
                    msg += f"PIC: {acars_pic.ljust(10)}\n"
                    
                    if alert_type == "UPDATED" and f.get('changes_text'):
                        msg += f"{html.escape(f['changes_text'])}\n"
                        
                    msg += "----------------------------------\n"
            
            acars_now = now_mst.replace(":", "").replace(" ", "").upper()
            msg += f"UPDATED: {acars_now}\n"
            msg += "**********************************\n"
            msg += "</pre>"

            print("Schedule changes detected! Sending ACARS to Telegram...")
            send_telegram(msg)
            
        elif not trigger_weather_dispatch:
            print("No changes and outside preflight window. Staying silent.")

        print("Sending active snapshot to TRMNL...")
        update_trmnl(trmnl_payload, now_mst, weather_decision)

        with open(MEMORY_FILE, "w") as f:
            json.dump(current_schedule, f, indent=4)
        print("Run complete. Memory updated.")

if __name__ == "__main__":
    run_scraper()
