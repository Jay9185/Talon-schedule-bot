import os
import sys
import json
import requests
import html
import math
import urllib.parse
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
TALON_LOGIN_URL = "https://apps4.talonsystems.com/tseta/servlet/content?module=home&page=homepg&zajael1120=42DC6E6C4E5A723E80D0BF0AC5A1C8AF"
MEMORY_FILE = "memory.json"

def get_smart_date(date_str, now_mst):
    try:
        current_year = now_mst.year
        clean_date = "".join(c for c in date_str if c.isalnum() or c.isspace()).strip()
        dt_str = f"{clean_date} {current_year}"
        dt = datetime.strptime(dt_str, "%d %b %Y").date()
        
        if dt.month == 12 and now_mst.month < 3: dt = dt.replace(year=current_year - 1)
        elif dt.month < 3 and now_mst.month == 12: dt = dt.replace(year=current_year + 1)
        
        delta = (dt - now_mst.date()).days
        
        if delta == 0: return f"Today, {date_str}"
        elif delta == 1: return f"Tomorrow, {date_str}"
        elif 1 < delta < 7: return f"This {dt.strftime('%A')}, {date_str}"
        elif delta == -1: return f"Yesterday, {date_str}"
        else: return date_str
    except:
        return date_str

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
        
        # CRITICAL FIX: Rest Periods have fewer columns because Talon merges the blank cells.
        if len(cols) < 5: continue
            
        start = cols[1].get_text(strip=True)
        stop = cols[2].get_text(strip=True)
        status = cols[3].get_text(strip=True)
        act_type = cols[4].get_text(strip=True)
        
        # Safely grab the remaining columns only if they exist
        resource = cols[5].get_text(strip=True) if len(cols) > 5 else "TBD"
        unit = cols[7].get_text(strip=True) if len(cols) > 7 else ("Rest Period" if act_type == "Rest Period" else "UNKNOWN")
        instructor = cols[8].get_text(strip=True) if len(cols) > 8 else "TBD"

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
            "lesson": unit if unit else "UNKNOWN", 
            "type": act_type,
            "remark": remark
        })
    return flights_data

def filter_old_flights(schedule):
    mst_tz = timezone(timedelta(hours=-7))
    now = datetime.now(mst_tz)
    cutoff_date = (now - timedelta(days=14)).date()
    current_year = now.year
    filtered_schedule = []
    
    for f in schedule:
        try:
            clean_date = "".join(c for c in f['date'] if c.isalnum() or c.isspace()).strip()
            dt_str = f"{clean_date} {current_year}"
            flight_dt = datetime.strptime(dt_str, "%d %b %Y").date()
            
            if flight_dt.month == 12 and now.month < 3: flight_dt = flight_dt.replace(year=current_year - 1)
            elif flight_dt.month < 3 and now.month == 12: flight_dt = flight_dt.replace(year=current_year + 1)
                
            if flight_dt >= cutoff_date: filtered_schedule.append(f)
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
        
        if flight_dt.month == 12 and now.month < 3: flight_dt = flight_dt.replace(year=current_year - 1)
        elif flight_dt.month < 3 and now.month == 12: flight_dt = flight_dt.replace(year=current_year + 1)
            
        return flight_dt > now
    except:
        return True 

def is_cancelled(f):
    status = f.get('status', '').lower()
    return 'cancel' in status or 'cnx' in status

def is_rest_period(f):
    return "Rest Period" in f.get('type', '') or "Rest Period" in f.get('lesson', '')

def is_actual_flight(f):
    act_type = f.get('type', '').lower()
    lesson = f.get('lesson', '').lower()
    if 'rest period' in act_type or 'rest period' in lesson: return False
    return act_type not in ['academic', 'oral', 'sim', 'ground', 'brief']

def evaluate_fatigue(target_flight, all_flights):
    warnings = []
    mst_tz = timezone(timedelta(hours=-7))
    now = datetime.now(mst_tz)
    current_year = now.year
    
    if is_cancelled(target_flight) or is_rest_period(target_flight): return []
    
    def parse_dt(d_str, t_str):
        clean_date = "".join(c for c in d_str if c.isalnum() or c.isspace()).strip()
        dt_str = f"{clean_date} {current_year} {t_str}"
        dt = datetime.strptime(dt_str, "%d %b %Y %H:%M")
        if dt.month == 12 and now.month < 3: dt = dt.replace(year=current_year - 1)
        elif dt.month < 3 and now.month == 12: dt = dt.replace(year=current_year + 1)
        return dt

    # 1. 12-Hour Duty Limit (Resets on Rest Periods)
    try:
        day_events = [f for f in all_flights if not is_cancelled(f) and f['date'] == target_flight['date']]
        
        # Sort events chronologically to accurately track the circuit breaker
        day_events.sort(key=lambda x: parse_dt(x['date'], x['time'].split("-")[0].strip()))
        
        duty_start = None
        max_duty_hours = 0.0
        worst_start = None
        worst_end = None
        
        for df in day_events:
            if is_rest_period(df):
                duty_start = None # CIRCUIT BREAKER: Duty resets here
                continue
                
            parts = df['time'].split("-")
            s_dt = parse_dt(df['date'], parts[0].strip())
            e_dt = parse_dt(df['date'], parts[1].split("(")[0].strip())
            if "(+1D)" in df['time']: e_dt += timedelta(days=1)
            
            if duty_start is None:
                duty_start = s_dt
                
            span = (e_dt - duty_start).total_seconds() / 3600
            
            if span > max_duty_hours:
                max_duty_hours = span
                worst_start = duty_start
                worst_end = e_dt
                
        if max_duty_hours > 12.0:
            warnings.append(f"Duty Day Span: {max_duty_hours:.1f} Hours ({worst_start.strftime('%H:%M')}-{worst_end.strftime('%H:%M')})")
    except Exception:
        pass

    # 2. 7-Day Continuous Check (Ignores days that ONLY have Rest Periods)
    try:
        working_flights = [f for f in all_flights if not is_cancelled(f) and not is_rest_period(f)]
        unique_dates = set()
        for f in working_flights:
            unique_dates.add(parse_dt(f['date'], "00:00").date())
            
        target_date = parse_dt(target_flight['date'], "00:00").date()
        if target_date in unique_dates:
            streak = 1
            
            check_date = target_date - timedelta(days=1)
            while check_date in unique_dates:
                streak += 1
                check_date -= timedelta(days=1)
                
            check_date = target_date + timedelta(days=1)
            while check_date in unique_dates:
                streak += 1
                check_date += timedelta(days=1)
                
            if streak > 7:
                warnings.append(f"Consecutive Days: {streak} Days (Requires 1 rest day in 7)")
    except Exception:
        pass
        
    return warnings

def get_trmnl_flights(schedule):
    mst_tz = timezone(timedelta(hours=-7))
    now = datetime.now(mst_tz)
    current_year = now.year
    trmnl_flights = []
    
    for f in schedule:
        if is_cancelled(f) or is_rest_period(f): continue
            
        try:
            time_parts = f['time'].split("-")
            if len(time_parts) < 2:
                trmnl_flights.append(f)
                continue
                
            stop_time_str = time_parts[1].split("(")[0].strip()
            clean_date = "".join(c for c in f['date'] if c.isalnum() or c.isspace()).strip()
            
            dt_str = f"{clean_date} {current_year} {stop_time_str}"
            stop_dt = datetime.strptime(dt_str, "%d %b %Y %H:%M").replace(tzinfo=mst_tz)
            
            if "(+1D)" in f['time']: stop_dt += timedelta(days=1)
            if stop_dt.month == 12 and now.month < 3: stop_dt = stop_dt.replace(year=current_year - 1)
            elif stop_dt.month < 3 and now.month == 12: stop_dt = stop_dt.replace(year=current_year + 1)
                
            if stop_dt > now: trmnl_flights.append(f)
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
            
            old_lesson = old_f.get('lesson', '').strip()
            new_lesson = f.get('lesson', '').strip()
            if old_lesson != new_lesson: changes.append(f"Lesson: {old_lesson} -> {new_lesson}")
            
            old_ip = old_f.get('ip', '').strip()
            new_ip = f.get('ip', '').strip()
            if old_ip != new_ip: changes.append(f"Instructor: {old_ip} -> {new_ip}")
            
            old_res = old_f.get('res', '').strip()
            new_res = f.get('res', '').strip()
            if old_res != new_res: changes.append(f"Aircraft: {old_res} -> {new_res}")
            
            old_status = old_f.get('status', '').strip()
            new_status = f.get('status', '').strip()
            if old_status != new_status: changes.append(f"Status: {old_status} -> {new_status}")
            
            old_remark = old_f.get('remark', '').strip()
            new_remark = f.get('remark', '').strip()
            if old_remark != new_remark: 
                if new_remark: changes.append(f"Remarks: '{new_remark}'")
                else: changes.append(f"Remarks Removed")

            if changes:
                f['changes_text'] = "\n".join([f"  • {c}" for c in changes])
                updated_alerts.append(f)

    for key, old_f in old_dict.items():
        if key not in new_dict:
            if is_future_flight(old_f):
                deleted_alerts.append(old_f)

    return new_alerts, updated_alerts, deleted_alerts

def evaluate_weather(start_dt, end_dt):
    runway_heading = 74 
    max_wind_limit = 15
    max_crosswind_limit = 10 
    
    reasons = []
    is_go = True
    current_wind = "N/A"
    forecast_wind = "N/A"
    max_crosswind_encountered = 0.0

    def run_limits_math(wind_dir, wind_speed, wind_gust, source_name):
        nonlocal is_go, max_crosswind_encountered
        
        wind_speed = wind_speed or 0
        wind_gust = wind_gust or 0
        max_speed = max(wind_speed, wind_gust)
        
        if max_speed > max_wind_limit:
            is_go = False
            reasons.append(f"[{source_name}] Wind limit exceeded ({max_speed} KT > {max_wind_limit} KT)")

        crosswind = 0.0
        if wind_dir == "VRB":
            crosswind = float(max_speed)
            max_crosswind_encountered = max(max_crosswind_encountered, crosswind)
            if crosswind > max_crosswind_limit:
                is_go = False
                reasons.append(f"[{source_name}] VRB crosswind exceeded ({crosswind:.1f} KT > {max_crosswind_limit} KT)")
        elif wind_dir is not None:
            angle_diff_radians = math.radians(wind_dir - runway_heading)
            crosswind = round(abs(max_speed * math.sin(angle_diff_radians)), 1)
            max_crosswind_encountered = max(max_crosswind_encountered, crosswind)
            
            if crosswind > max_crosswind_limit:
                is_go = False
                reasons.append(f"[{source_name}] Crosswind exceeded ({crosswind:04.1f} KT > {max_crosswind_limit} KT)")
                
        dir_str = "VRB" if wind_dir == "VRB" else str(wind_dir).zfill(3) if wind_dir else "000"
        return f"{dir_str} @ {wind_speed} KT" + (f" G {wind_gust} KT" if wind_gust else "")

    def parse_api_time(t_val):
        if isinstance(t_val, int): return datetime.fromtimestamp(t_val, tz=timezone.utc)
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
                                fcst.get("wdir"), fcst.get("wspd"), fcst.get("wgst"), f"TAF {period_start_z}Z"
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
        return {"status": "ERROR", "alerts": [f"System Error: {str(e)[:20]}"]}

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

def sync_gcal(schedule):
    webhook_url = os.environ.get("GCAL_WEBHOOK_URL")
    if not webhook_url: return
    try: requests.post(webhook_url, json={"schedule": schedule}, timeout=15)
    except: pass

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
    except: pass

def run_scraper():
    username = os.environ.get("TALON_USER")
    password = os.environ.get("TALON_PASS")
    
    mst_tz = timezone(timedelta(hours=-7))
    now_mst_obj = datetime.now(mst_tz)
    now_mst = now_mst_obj.strftime("%d %b %Y %I:%M %p MST")

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
            page.goto(TALON_LOGIN_URL, timeout=30000, wait_until="networkidle")
            page.fill("input[name='uname']", username, timeout=5000)
            page.locator("input[name='password']").click() 
            page.wait_for_timeout(500) 
            page.fill("input[name='password']", password, timeout=5000, force=True) 
            page.click("input[id='butlogin']", timeout=5000)
            
            page.wait_for_timeout(5000) 

            current_url = page.url
            parsed_url = urllib.parse.urlparse(current_url)
            qs = urllib.parse.parse_qs(parsed_url.query)
            token_key = next((k for k in qs.keys() if 'zajael' in k.lower()), None)
            
            if token_key:
                token_val = qs[token_key][0]
                direct_sched_url = f"https://apps4.talonsystems.com/tseta/servlet/content?module=home&filterForm=1&page=homepg&content_type=mysched&showImg=&maxdayshow=7&{token_key}={token_val}"
                page.goto(direct_sched_url, timeout=20000, wait_until="networkidle")
                page.wait_for_timeout(3000)
            else:
                for frame in page.frames:
                    try:
                        tab = frame.locator("text='My Schedule'")
                        if tab.count() > 0:
                            tab.first.click(timeout=3000)
                            page.wait_for_timeout(4000)
                            break
                    except:
                        continue

            for frame in page.frames:
                try:
                    frame.wait_for_selector("table#tblSchedListS", timeout=10000)
                    html_dump = frame.content()
                    break 
                except:
                    continue
            
            if not html_dump:
                error_msg = "<pre>\n========================================\n        AEROGUARD SCRAPER ALERT       \n========================================\nStatus:      Failed to locate schedule\nAction:      Check GitHub Action logs\n========================================\n</pre>"
                send_telegram(error_msg)

        except Exception as e:
            print(f"Encountered a navigation issue: {e}")
        finally:
            browser.close()

    if html_dump:
        current_schedule = extract_schedule(html_dump)
        if not current_schedule: return

        current_schedule = filter_old_flights(current_schedule)
        old_schedule = filter_old_flights(old_schedule)
        
        new_flights, updated_flights, deleted_flights = compare_schedules(old_schedule, current_schedule)

        trmnl_payload = get_trmnl_flights(current_schedule)
        weather_decision = {"status": "NO FLIGHTS", "alerts": []}
        trigger_weather_dispatch = False
        target_flight_details = None
        
        active_future_flights = [f for f in current_schedule if is_future_flight(f) and not is_cancelled(f) and not is_rest_period(f)]
        
        weather_applicable_flights = [f for f in active_future_flights if is_actual_flight(f)]
        
        if weather_applicable_flights:
            next_f = weather_applicable_flights[0]
            current_year = now_mst_obj.year
            try:
                time_parts = next_f['time'].split("-")
                start_time_str = time_parts[0].strip()
                end_time_str = time_parts[1].split("(")[0].strip()
                
                clean_date = "".join(c for c in next_f['date'] if c.isalnum() or c.isspace()).strip()
                
                start_dt_str = f"{clean_date} {current_year} {start_time_str}"
                end_dt_str = f"{clean_date} {current_year} {end_time_str}"
                
                start_dt = datetime.strptime(start_dt_str, "%d %b %Y %H:%M").replace(tzinfo=mst_tz)
                end_dt = datetime.strptime(end_dt_str, "%d %b %Y %H:%M").replace(tzinfo=mst_tz)
                
                if "(+1D)" in next_f['time']: end_dt += timedelta(days=1)
                
                if start_dt.month == 12 and now_mst_obj.month < 3:
                    start_dt = start_dt.replace(year=current_year - 1)
                    end_dt = end_dt.replace(year=current_year - 1)
                elif start_dt.month < 3 and now_mst_obj.month == 12:
                    start_dt = start_dt.replace(year=current_year + 1)
                    end_dt = end_dt.replace(year=current_year + 1)
                    
                weather_decision = evaluate_weather(start_dt, end_dt)
                
                hours_until_flight = (start_dt - now_mst_obj).total_seconds() / 3600
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
                weather_decision = evaluate_weather(None, None)
        
        is_manual_run = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        
        if is_manual_run:
            if active_future_flights:
                msg = "<pre>\n"
                msg += "========================================\n"
                msg += "        AEROGUARD MASTER SCHEDULE       \n"
                msg += "========================================\n"
                for f in active_future_flights:
                    smart_date = get_smart_date(f['date'], now_mst_obj)
                    msg += f"Date:        {html.escape(smart_date)}\n"
                    msg += f"Block:       {html.escape(f['time'])}\n"
                    msg += f"Lesson:      {html.escape(f['lesson'])}\n"
                    msg += f"Type:        {html.escape(f['type'])}\n"
                    msg += f"Aircraft:    {html.escape(f['res'])}\n"
                    msg += f"Instructor:  {html.escape(f['ip'])}\n"
                    msg += f"Status:      {html.escape(f['status'])}\n"
                    if f.get('remark'):
                        msg += f"Remarks:     {html.escape(f['remark'])}\n"
                        
                    fatigue_warns = evaluate_fatigue(f, current_schedule)
                    if fatigue_warns:
                        msg += "\n⚠️ FATIGUE WARNING:\n"
                        for w in fatigue_warns:
                            msg += f"- {w}\n"
                            
                    msg += "----------------------------------------\n"
                msg += f"Updated: {now_mst}\n"
                msg += "========================================\n"
                msg += "</pre>"

                if len(msg) > 4000:
                    msg = msg[:3900] + "\n...[TRUNCATED]\n========================================\n</pre>"

                send_telegram(msg)
                
        if trigger_weather_dispatch and target_flight_details:
            smart_date = get_smart_date(target_flight_details['date'], now_mst_obj)
            msg = "<pre>\n"
            msg += "========================================\n"
            msg += "        AEROGUARD DISPATCH RELEASE      \n"
            msg += "========================================\n"
            msg += f"Date:        {html.escape(smart_date)}\n"
            msg += f"Block:       {html.escape(target_flight_details['time'])}\n"
            msg += f"Lesson:      {html.escape(target_flight_details['lesson'])} ({html.escape(target_flight_details['type'])})\n"
            msg += f"Aircraft:    {html.escape(target_flight_details['res'])}\n"
            msg += f"Instructor:  {html.escape(target_flight_details['ip'])}\n"
            msg += f"Status:      {html.escape(target_flight_details['status'])}\n"
            msg += f"Remarks:     {html.escape(target_flight_details.get('remark', 'None'))}\n\n"
            
            msg += f"WEATHER ANALYSIS: {weather_decision['status']}\n"
            msg += "----------------------------------------\n"
            msg += f"Current Wind:   {weather_decision.get('metar_wind', 'N/A')}\n"
            msg += f"Forecast Wind:  {weather_decision.get('taf_wind', 'N/A')}\n"
            msg += f"Max Crosswind:  {weather_decision.get('max_crosswind_kt', 0):04.1f} KT (Rwy 07/25)\n"
            
            if weather_decision.get("alerts"):
                msg += "\nWARNINGS:\n"
                for alert in weather_decision["alerts"]:
                    msg += f"- {html.escape(alert)}\n"
            msg += "========================================\n"
            msg += "</pre>"

            send_telegram(msg)

        if new_flights or updated_flights or deleted_flights:
            alerts_by_date = {}
            for f in new_flights: alerts_by_date.setdefault(f['date'], []).append((f, "NEW"))
            for f in updated_flights: alerts_by_date.setdefault(f['date'], []).append((f, "UPDATED"))
            for f in deleted_flights: alerts_by_date.setdefault(f['date'], []).append((f, "DELETED"))

            msg = "<pre>\n"
            msg += "========================================\n"
            msg += "       AEROGUARD SCHEDULING ALERT       \n"
            msg += "========================================\n"
            for date in sorted(alerts_by_date.keys()):
                smart_date = get_smart_date(date, now_mst_obj)
                msg += f"{html.escape(smart_date)}\n"
                msg += "----------------------------------------\n"
                for f, alert_type in alerts_by_date[date]:
                    action = "CANCELED" if is_cancelled(f) else ("ADDED" if alert_type == "NEW" else ("REMOVED" if alert_type == "DELETED" else "MODIFIED"))
                    
                    msg += f"Action:      {action}\n"
                    msg += f"Block:       {html.escape(f['time'])}\n"
                    msg += f"Lesson:      {html.escape(f['lesson'])}\n"
                    msg += f"Aircraft:    {html.escape(f['res'])}\n"
                    msg += f"Instructor:  {html.escape(f['ip'])}\n"
                    
                    if is_cancelled(f):
                        msg += f"Status:      {html.escape(f['status'])} [CNX]\n"
                    else:
                        msg += f"Status:      {html.escape(f['status'])}\n"
                        
                    if alert_type == "UPDATED" and f.get('changes_text'):
                        msg += f"Changes:\n{html.escape(f['changes_text'])}\n"
                        
                    if alert_type in ["NEW", "UPDATED"] and not is_cancelled(f) and not is_rest_period(f):
                        fatigue_warns = evaluate_fatigue(f, current_schedule)
                        if fatigue_warns:
                            msg += "\n⚠️ FATIGUE / LEGALITY WARNING:\n"
                            for w in fatigue_warns:
                                msg += f"- {w}\n"
                                
                    msg += "----------------------------------------\n"
            msg += f"Updated: {now_mst}\n"
            msg += "========================================\n"
            msg += "</pre>"

            send_telegram(msg)

        sync_gcal(current_schedule)
        update_trmnl(trmnl_payload, now_mst, weather_decision)

        with open(MEMORY_FILE, "w") as f:
            json.dump(current_schedule, f, indent=4)
        print("Run complete. Memory updated.")

if __name__ == "__main__":
    run_scraper()
