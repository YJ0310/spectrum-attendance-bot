#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UM SPeCTRUM (Moodle) Automated Attendance Taker & Watcher
Supports:
- Persistent Chrome profile with Microsoft OIDC SSO auto-refresh
- Fast HTTP polling via requests + BeautifulSoup
- Automatic selection of 'Present' and form submission
- Password submission via /password <code>
- Full weekly view fetching for Telegram /status
- Telegram Bot (@takoo_helper_bot) notifications
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import telegram_bot

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def get_state_dir() -> str:
    sdir = os.environ.get("SPECTRUM_STATE_DIR")
    if not sdir:
        data_dir = os.path.join(BASE_DIR, "data")
        sdir = data_dir if os.path.exists(data_dir) else os.path.expanduser("~/.config/spectrum")
    os.makedirs(sdir, exist_ok=True)
    return sdir


STATE_DIR = get_state_dir()
COOKIE_FILE = os.path.join(STATE_DIR, "cookies.json")
CHROME_PROFILE_DIR = os.path.join(STATE_DIR, "chrome_profile")
LOG_FILE = os.path.join(STATE_DIR, "attendance.log")
PENDING_PASSWORD_FILE = os.path.join(STATE_DIR, "pending_password.json")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

load_dotenv(os.path.join(BASE_DIR, ".env"))
SPECTRUM_BASE_URL = os.environ.get("SPECTRUM_BASE_URL", "https://spectrum.um.edu.my").rstrip("/")


def normalize_spectrum_url(url: str) -> str:
    """Replaces spectrum.um.edu.my with SPECTRUM_BASE_URL if custom proxy is configured."""
    if not url:
        return SPECTRUM_BASE_URL
    if SPECTRUM_BASE_URL != "https://spectrum.um.edu.my" and "spectrum.um.edu.my" in url:
        return url.replace("https://spectrum.um.edu.my", SPECTRUM_BASE_URL).replace("http://spectrum.um.edu.my", SPECTRUM_BASE_URL)
    return url


def log(msg: str):
    """Prints a timestamped log message and appends it to ~/.config/spectrum/attendance.log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify_macos(title: str, message: str):
    """Displays a native macOS desktop notification if on Mac."""
    if sys.platform != "darwin":
        return
    try:
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        script = f'display notification "{safe_msg}" with title "{safe_title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "courses": [
            {
                "name": "Lecture Attendance-DK1, Thursday, 4-6pm",
                "url": "https://spectrum.um.edu.my/mod/attendance/view.php?id=1121957",
                "status_label": "Present",
                "schedule": [
                    {
                        "day": "Thu",
                        "hour": 16,
                        "minute": 0
                    }
                ],
            }
        ],
        "poll_interval_seconds": 60,
        "watch_timeout_minutes": 120,
    }


def save_cookies(cookies_dict: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated_at": datetime.now().isoformat(),
                "cookies": cookies_dict,
            },
            f,
            indent=2,
        )
    log(f"💾 Saved session cookies to {COOKIE_FILE}")


def load_cookies() -> dict:
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cookies = data.get("cookies", {})
                if cookies:
                    return cookies
        except Exception:
            pass
    env_sess = os.environ.get("MOODLE_SESSION", "").strip()
    if env_sess:
        cookies = {"MoodleSession": env_sess}
        env_cs1 = os.environ.get("COOKIESESSION1", "678B28C54C272EA66C4BF98F4CFDDA60").strip()
        if env_cs1:
            cookies["cookiesession1"] = env_cs1
        return cookies
    return {}


def build_http_session(cookies_dict: dict = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    cookies = cookies_dict if cookies_dict is not None else load_cookies()
    # Set cookies unconditionally on the session without domain restrictions so requests attaches them to proxy hosts
    for k, v in cookies.items():
        s.cookies.set(k, v)
    parsed_base = urlparse(SPECTRUM_BASE_URL)
    domains = {"spectrum.um.edu.my"}
    if parsed_base.netloc:
        domains.add(parsed_base.netloc.split(":")[0])
    for d in domains:
        for k, v in cookies.items():
            s.cookies.set(k, v, domain=d)
    return s


def is_authenticated_html(url: str, html_text: str) -> bool:
    """Checks whether the response is an authenticated SPeCTRUM page rather than a login/OIDC page."""
    parsed = urlparse(url)
    if "login.microsoftonline.com" in parsed.netloc:
        return False
    if "/login/" in parsed.path or "/auth/oidc/" in parsed.path:
        return False
    if "Log in to the site" in html_text or 'href="https://spectrum.um.edu.my/login/index.php"' in html_text:
        return False
    # Fail if login form is present
    if 'name="username"' in html_text and 'name="password"' in html_text and '<form' in html_text:
        return False
    return True


def _create_chrome_driver(headless: bool = True):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    options = Options()

    chrome_bin = (
        os.environ.get("CHROME_BIN")
        or os.environ.get("GOOGLE_CHROME_BIN")
        or os.environ.get("CHROMIUM_PATH")
    )
    if chrome_bin:
        options.binary_location = chrome_bin

    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--window-size=1280,860")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        options.add_argument("--headless=new")

    # Support Linux Docker / cloud environments
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--single-process")

    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
    service = Service(executable_path=chromedriver_path) if chromedriver_path else Service()

    return webdriver.Chrome(service=service, options=options)


def _try_autofill_microsoft_sso(driver, email: str = None, password: str = None):
    """Optionally auto-fills email and password (from arguments or .env) if on Microsoft login page."""
    em = (email or os.environ.get("UM_EMAIL", "")).strip()
    pw = (password or os.environ.get("UM_PASSWORD", "")).strip()

    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    try:
        cur_url = driver.current_url
        if "login.microsoftonline.com" not in cur_url:
            return

        # Check for account picker tiles if previously signed in
        tiles = driver.find_elements(By.CSS_SELECTOR, "div.tile, div.table-row, div[data-test-id]")
        for t in tiles:
            if em and em.lower() in t.text.lower():
                t.click()
                time.sleep(2)
                break

        if em:
            email_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="email"][name="loginfmt"]')
            if email_inputs and email_inputs[0].is_displayed():
                val = email_inputs[0].get_attribute("value") or ""
                if not val:
                    log(f"🔐 Auto-filling UM_EMAIL ({em})...")
                    email_inputs[0].clear()
                    email_inputs[0].send_keys(em)
                    email_inputs[0].send_keys(Keys.RETURN)
                    time.sleep(2)

        if pw:
            pwd_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="password"][name="passwd"]')
            if pwd_inputs and pwd_inputs[0].is_displayed():
                val = pwd_inputs[0].get_attribute("value") or ""
                if not val:
                    log("🔐 Auto-filling UM_PASSWORD...")
                    pwd_inputs[0].clear()
                    pwd_inputs[0].send_keys(pw)
                    pwd_inputs[0].send_keys(Keys.RETURN)
                    time.sleep(2)

        # Check for "Stay signed in?" Yes button
        yes_btn = driver.find_elements(By.CSS_SELECTOR, 'input[type="submit"][id="idSIButton9"], input[value="Yes"]')
        if yes_btn and yes_btn[0].is_displayed():
            yes_btn[0].click()
            time.sleep(2)
    except Exception:
        pass


def login_or_refresh_session(
    target_url: str,
    force_interactive: bool = False,
    email: str = None,
    password: str = None,
) -> dict:
    """
    Uses persistent Chrome profile to refresh MoodleSession via Microsoft OIDC.
    First tries headless mode. If interaction / 2FA is needed, opens a visible window if supported.
    """
    if not force_interactive:
        log("🔄 Refreshing SPeCTRUM session in headless Chrome using persistent SSO profile...")
        driver = None
        try:
            driver = _create_chrome_driver(headless=True)
            driver.get(target_url)
            for _ in range(12):
                time.sleep(1)
                _try_autofill_microsoft_sso(driver, email=email, password=password)
                cur_url = driver.current_url
                html_text = driver.page_source
                if is_authenticated_html(cur_url, html_text) and any(
                    c["name"] == "MoodleSession" for c in driver.get_cookies()
                ):
                    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
                    save_cookies(cookies)
                    log("✅ Silently refreshed SPeCTRUM session via headless Chrome!")
                    return cookies
        except Exception as e:
            log(f"⚠️ Headless session refresh notice: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    # Visible browser fallback (macOS/desktop)
    if os.environ.get("HEADLESS_ONLY", "").lower() in ("1", "true"):
        log("⚠️ Headless-only mode active; skipping visible browser fallback.")
        return {}

    log("🌐 Opening Chrome for UM Microsoft SSO login...")
    log("💡 Please complete login in the opened Chrome window (and click 'Yes' on 'Stay signed in?').")
    driver = None
    try:
        driver = _create_chrome_driver(headless=False)
        driver.get(target_url)

        for second in range(1, 300):
            time.sleep(1)
            _try_autofill_microsoft_sso(driver, email=email, password=password)
            try:
                cur_url = driver.current_url
                html_text = driver.page_source
            except Exception:
                continue

            if is_authenticated_html(cur_url, html_text):
                raw_cookies = driver.get_cookies()
                if any(c["name"] == "MoodleSession" for c in raw_cookies):
                    cookies = {c["name"]: c["value"] for c in raw_cookies}
                    save_cookies(cookies)
                    log("🎉 Login detected and session cookies saved!")
                    return cookies

            if second % 10 == 0:
                log(f"⏳ Waiting for UM SPeCTRUM login to finish... ({second}s elapsed)")

        log("❌ Timed out waiting for login in Chrome.")
        return {}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


DAY_NAME_MAP = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def extract_course_id(course: dict) -> str:
    """Extracts the numeric course ID from course dict or its URL."""
    if course.get("id"):
        return str(course["id"])
    url = course.get("url", "")
    m = re.search(r"id=(\d+)", url)
    if m:
        return m.group(1)
    return ""


def format_schedule_string(schedule_list: list) -> str:
    """Formats schedule array into human-readable timeline string."""
    if not schedule_list:
        return ""
    if len(schedule_list) == 1:
        s = schedule_list[0]
        day_full = DAY_NAME_MAP.get(str(s.get("day", "")).lower()[:3], s.get("day", ""))
        h = int(s.get("hour", 0))
        m = int(s.get("minute", 0))
        return f"{day_full} {h:02d}:{m:02d}"

    days = [str(s.get("day", "")) for s in schedule_list]
    if len(days) == 5 and [d[:3].lower() for d in days] == ["mon", "tue", "wed", "thu", "fri"]:
        s = schedule_list[0]
        h = int(s.get("hour", 0))
        m = int(s.get("minute", 0))
        return f"Mon-Fri {h:02d}:{m:02d}"

    parts = []
    for s in schedule_list:
        day_full = DAY_NAME_MAP.get(str(s.get("day", "")).lower()[:3], s.get("day", ""))
        h = int(s.get("hour", 0))
        m = int(s.get("minute", 0))
        parts.append(f"{day_full} {h:02d}:{m:02d}")
    return ", ".join(parts)


def parse_attlist_stats(soup: BeautifulSoup) -> dict:
    """
    Parses table.attlist for overall attendance statistics:
      - taken_sessions (int)
      - points_achieved (int)
      - points_total (int)
      - points_ratio (str)
      - attendance_rate (float)
      - percentage_label (str)
    """
    stats = {
        "taken_sessions": 0,
        "points_achieved": 0,
        "points_total": 0,
        "points_ratio": "0 / 0",
        "attendance_rate": 100.0,
        "percentage_label": "100.0%",
    }
    attlist = soup.select_one("table.attlist")
    if not attlist:
        return stats

    for tr in attlist.select("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).lower()
        val = cells[1].get_text(" ", strip=True)
        is_taken = ("taken session" in label or "sesi diambil" in label)
        not_other = "point" not in label and "mata" not in label and "percent" not in label and "peratus" not in label
        if is_taken and not_other:
            m = re.search(r"(\d+)", val)
            if m:
                try:
                    stats["taken_sessions"] = int(m.group(1))
                except Exception:
                    pass
        elif "point" in label or "mata" in label:
            stats["points_ratio"] = val
            m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", val)
            if m:
                try:
                    stats["points_achieved"] = int(float(m.group(1)))
                    stats["points_total"] = int(float(m.group(2)))
                except Exception:
                    pass
        elif "percentage" in label or "peratus" in label or "%" in val:
            stats["percentage_label"] = val
            m = re.search(r"(\d+(?:\.\d+)?)", val)
            if m:
                try:
                    stats["attendance_rate"] = float(m.group(1))
                except Exception:
                    pass

    return stats


def parse_generaltable_sessions(soup: BeautifulSoup, course_id: str = "") -> tuple[list[dict], list[str]]:
    """
    Parses table.generaltable or table.attwidth rows into structured session dictionaries
    and raw text summaries.
    """
    parsed_sessions = []
    sessions_summary = []

    table = soup.select_one("table.generaltable, table.attwidth")
    if not table:
        for t in soup.find_all("table"):
            headers = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
            if any(h in ("date", "time", "status", "points", "description", "tarikh") for h in headers):
                table = t
                break

    if not table:
        return parsed_sessions, sessions_summary

    rows = table.select("tbody tr")
    for idx, tr in enumerate(rows):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 3:
            continue

        raw_text = " | ".join(c for c in cells if c)
        sessions_summary.append(raw_text)

        date_col = cells[0] if len(cells) > 0 else ""
        desc_col = cells[1] if len(cells) > 1 else ""
        status_col = cells[2] if len(cells) > 2 else ""
        points_col = cells[3] if len(cells) > 3 else ""
        remarks_col = cells[4] if len(cells) > 4 else ""

        # Map weekday
        day_match = re.match(r"^([A-Za-z]{3})", date_col)
        day_abbr = day_match.group(1).lower() if day_match else ""
        full_day = DAY_NAME_MAP.get(day_abbr, day_abbr.capitalize() if day_abbr else "")

        can_submit = False
        link_el = tr.find("a", href=True)
        if link_el:
            href = link_el.get("href", "")
            t_text = link_el.get_text(" ", strip=True).lower()
            if "attendance.php" in href or "submit" in t_text or "hantar" in t_text:
                can_submit = True

        session_obj = {
            "id": f"{course_id}_{idx}" if course_id else str(idx),
            "date": date_col,
            "day": full_day,
            "description": desc_col,
            "status": status_col,
            "points": points_col,
            "remarks": remarks_col,
            "can_submit": can_submit,
            "raw_text": raw_text,
        }
        parsed_sessions.append(session_obj)

    return parsed_sessions, sessions_summary


def parse_attendance_view(html_text: str, base_url: str, course_id: str = "") -> dict:
    """
    Parses the Moodle mod_attendance view.php HTML.
    Returns:
      - course_title: str
      - submit_links: list of dicts [{"url": ..., "text": ..., "row_text": ...}]
      - sessions_summary: list of strings summarizing recent/today session rows
      - parsed_sessions: list of structured session dicts
      - stats: dict of metrics from table.attlist
    """
    soup = BeautifulSoup(html_text, "html.parser")

    title_el = soup.select_one("h1") or soup.select_one(".page-header-headings") or soup.select_one("title")
    course_title = title_el.get_text(" ", strip=True) if title_el else "SPeCTRUM Course"

    submit_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if "mod/attendance/attendance.php" in href or "submit attendance" in text.lower() or "hantar kehadiran" in text.lower():
            full_url = normalize_spectrum_url(urljoin(base_url, href))
            tr = a.find_parent("tr")
            row_text = tr.get_text(" | ", strip=True) if tr else text
            submit_links.append({
                "url": full_url,
                "text": text or "Submit attendance",
                "row_text": row_text,
            })

    stats = parse_attlist_stats(soup)
    parsed_sessions, sessions_summary = parse_generaltable_sessions(soup, course_id=course_id)

    return {
        "course_title": course_title,
        "submit_links": submit_links,
        "sessions_summary": sessions_summary,
        "parsed_sessions": parsed_sessions,
        "stats": stats,
    }


def save_pending_password(data: dict):
    """Saves details of a session currently waiting for a password."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PENDING_PASSWORD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_pending_password() -> dict:
    if os.path.exists(PENDING_PASSWORD_FILE):
        try:
            with open(PENDING_PASSWORD_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def clear_pending_password():
    if os.path.exists(PENDING_PASSWORD_FILE):
        try:
            os.remove(PENDING_PASSWORD_FILE)
        except Exception:
            pass


def submit_attendance_form(
    session: requests.Session,
    submit_url: str,
    preferred_label: str = "Present",
    password: str = None,
    course_name: str = "",
    row_text: str = ""
) -> tuple[bool, str]:
    """
    Visits the Moodle attendance.php URL and submits the form with 'Present' selected.
    If a password is required and not provided, saves pending state and returns False with PASSWORD_REQUIRED.
    """
    submit_url = normalize_spectrum_url(submit_url)
    log(f"🚀 Opening attendance submission link: {submit_url}")
    resp = session.get(submit_url, allow_redirects=True, timeout=20)

    # 1-click auto-recorded on GET
    if "mod/attendance/view.php" in resp.url and "mod/attendance/attendance.php" not in resp.url:
        clear_pending_password()
        return True, "Attendance automatically recorded via 1-click link!"

    soup = BeautifulSoup(resp.text, "html.parser")

    target_form = None
    for form in soup.find_all("form"):
        action = form.get("action", "")
        if "attendance.php" in action or form.find("input", {"name": "status"}) or form.find("input", {"name": "sessid"}):
            target_form = form
            break

    if not target_form:
        alert = soup.select_one(".alert, .notification, #user-notifications")
        alert_text = alert.get_text(" ", strip=True) if alert else "No attendance form found on page."
        return False, alert_text

    action_url = normalize_spectrum_url(urljoin(resp.url, target_form.get("action") or submit_url))
    payload = {}

    for inp in target_form.find_all("input"):
        inp_type = (inp.get("type") or "text").lower()
        name = inp.get("name")
        if not name:
            continue
        if inp_type in ("hidden", "text", "password"):
            payload[name] = inp.get("value", "")
        elif inp_type == "submit" and name == "submitbutton":
            payload[name] = inp.get("value", "Save changes")

    if "submitbutton" not in payload:
        payload["submitbutton"] = "Save changes"

    # Check for password field
    pwd_inp = target_form.find("input", {"name": re.compile(r"studentpassword|password|qrpass", re.I)})
    if pwd_inp:
        pwd_name = pwd_inp.get("name")
        if password:
            log(f"🔑 Filling password for '{pwd_name}'...")
            payload[pwd_name] = password.strip()
        else:
            log(f"⚠️ Form requires a password ('{pwd_name}')! Saving pending password request...")
            save_pending_password({
                "course_name": course_name,
                "row_text": row_text,
                "submit_url": submit_url,
                "preferred_label": preferred_label,
                "password_field": pwd_name,
                "created_at": datetime.now().isoformat(),
            })
            return False, "PASSWORD_REQUIRED"

    # Find radio buttons for status
    radios = target_form.find_all("input", {"type": "radio"})
    if not radios:
        return False, "Attendance form found, but no status radio options were present."

    chosen_radio = None
    chosen_label_text = ""
    available_options = []

    for r in radios:
        r_id = r.get("id")
        r_name = r.get("name", "status")
        r_val = r.get("value")

        label_text = ""
        if r_id:
            lbl = target_form.find("label", {"for": r_id})
            if lbl:
                label_text = lbl.get_text(" ", strip=True)
        if not label_text:
            parent_lbl = r.find_parent("label") or r.find_parent(class_=re.compile(r"fitem|form-check|felement"))
            if parent_lbl:
                label_text = parent_lbl.get_text(" ", strip=True)

        available_options.append(f"{label_text or 'Option'} (value={r_val})")

        if preferred_label.lower() in label_text.lower() or "hadir" in label_text.lower():
            chosen_radio = (r_name, r_val)
            chosen_label_text = label_text
            break

    if not chosen_radio and radios:
        first_r = radios[0]
        chosen_radio = (first_r.get("name", "status"), first_r.get("value"))
        chosen_label_text = f"First option ({available_options[0]})"

    log(f"📋 Available status options: {', '.join(available_options)}")
    log(f"☑️ Selecting '{chosen_label_text}' ({chosen_radio[0]}={chosen_radio[1]}) and submitting...")

    payload[chosen_radio[0]] = chosen_radio[1]

    post_resp = session.post(action_url, data=payload, allow_redirects=True, timeout=20)
    post_soup = BeautifulSoup(post_resp.text, "html.parser")

    alert_els = post_soup.select(".alert, .notification, #user-notifications")
    alerts = [el.get_text(" ", strip=True) for el in alert_els if el.get_text(strip=True)]
    alert_summary = " | ".join(alerts)

    if "mod/attendance/view.php" in post_resp.url or "recorded" in post_resp.text.lower() or "direkodkan" in post_resp.text.lower():
        clear_pending_password()
        return True, alert_summary or f"Marked '{chosen_label_text}' successfully!"

    err = post_soup.select_one(".error, .invalid-feedback, .ferror")
    if err and err.get_text(strip=True):
        return False, f"Form error: {err.get_text(' ', strip=True)}"

    return False, f"Unexpected response after POST. {alert_summary}"


def check_and_submit_course(course: dict, password: str = None, force_interactive_login: bool = False) -> dict:
    """
    Checks a single course's attendance page, refreshes login if needed, and submits attendance if open.
    Returns dict with keys: status ('submitted', 'password_required', 'already_taken_or_closed', 'auth_failed', 'error'), message
    """
    url = normalize_spectrum_url(course["url"])
    name = course.get("name", url)
    preferred_label = course.get("status_label", "Present")

    log(f"🔎 Checking attendance for: {name} ({url})")

    cookies = load_cookies()
    if force_interactive_login or not cookies:
        cookies = login_or_refresh_session(url, force_interactive=force_interactive_login)
        if not cookies:
            return {"status": "auth_failed", "message": "Could not obtain SPeCTRUM session cookies.", "course": name}

    session = build_http_session(cookies)
    try:
        resp = session.get(url, allow_redirects=True, timeout=20)
    except Exception as e:
        return {"status": "error", "message": f"Network error fetching {url}: {e}", "course": name}

    if not is_authenticated_html(resp.url, resp.text):
        log("🔑 Cached MoodleSession expired. Refreshing session...")
        cookies = login_or_refresh_session(url, force_interactive=False)
        if not cookies:
            return {"status": "auth_failed", "message": "Session expired and refresh failed.", "course": name}
        session = build_http_session(cookies)
        resp = session.get(url, allow_redirects=True, timeout=20)
        if not is_authenticated_html(resp.url, resp.text):
            return {"status": "auth_failed", "message": "Still unauthenticated after session refresh.", "course": name}

    info = parse_attendance_view(resp.text, resp.url)
    log(f"📘 Course Page: {info['course_title']}")

    if info["sessions_summary"]:
        log(f"📅 Found {len(info['sessions_summary'])} session row(s). Current/Taken sessions:")
        for row in info["sessions_summary"][:5]:
            log(f"   • {row}")

    if not info["submit_links"]:
        log("⏸️ No active 'Submit attendance' link right now (either not open yet or already recorded).")
        return {
            "status": "already_taken_or_closed",
            "message": "No active 'Submit attendance' link on page.",
            "course": name,
            "title": info["course_title"],
            "sessions": info["sessions_summary"][:5],
        }

    submitted_any = False
    needs_password = False
    messages = []

    for link in info["submit_links"]:
        log(f"🎯 Found active attendance session! Row: {link['row_text']}")
        ok, msg = submit_attendance_form(
            session,
            link["url"],
            preferred_label=preferred_label,
            password=password,
            course_name=info["course_title"],
            row_text=link["row_text"],
        )
        if ok:
            log(f"✅ SUCCESS: {msg}")
            notify_macos("SPeCTRUM Attendance Recorded ✅", f"{info['course_title']}: {msg}")
            telegram_bot.notify_attendance_recorded(info["course_title"], link["row_text"])
            submitted_any = True
            messages.append(msg)
        elif msg == "PASSWORD_REQUIRED":
            needs_password = True
            messages.append("Password required to complete attendance submission.")
            telegram_bot.notify_password_required(info["course_title"], link["row_text"])
        else:
            log(f"❌ Failed to submit attendance: {msg}")
            messages.append(msg)

    if submitted_any:
        return {"status": "submitted", "message": "; ".join(messages), "course": name, "title": info["course_title"]}
    if needs_password:
        return {"status": "password_required", "message": "Attendance requires password. Send /password <code> to submit.", "course": name}
    return {"status": "error", "message": "; ".join(messages), "course": name}


def submit_pending_password(password: str) -> tuple[bool, str]:
    """
    Submits a password for any pending attendance session.
    Called when the user sends /password <code> to the Telegram bot.
    """
    pending = get_pending_password()
    if not pending or not pending.get("submit_url"):
        return False, "No active attendance session is currently waiting for a password."

    submit_url = pending["submit_url"]
    course_name = pending.get("course_name", "SPeCTRUM Course")
    pref_label = pending.get("preferred_label", "Present")

    cookies = load_cookies()
    session = build_http_session(cookies)

    log(f"🔑 Submitting password '{password}' for pending session: {course_name}")
    ok, msg = submit_attendance_form(
        session,
        submit_url,
        preferred_label=pref_label,
        password=password,
        course_name=course_name,
        row_text=pending.get("row_text", ""),
    )

    if ok:
        notify_macos("SPeCTRUM Attendance Recorded ✅", f"{course_name}: Password accepted!")
        telegram_bot.notify_attendance_recorded(course_name, pending.get("row_text", ""), points="Password Accepted")
        clear_pending_password()
        return True, f"Success: Attendance recorded for {course_name}!"
    return False, f"Failed: {msg}"


def fetch_weekly_sessions(course: dict) -> list[str]:
    """
    Fetches the attendance sessions scheduled for the entire current week.
    Uses view=2 (Weeks) or filters view=5.
    """
    base_url = normalize_spectrum_url(course["url"])
    sep = "&" if "?" in base_url else "?"
    weekly_url = f"{base_url}{sep}view=2"

    cookies = load_cookies()
    session = build_http_session(cookies)

    try:
        resp = session.get(weekly_url, allow_redirects=True, timeout=20)
        if not is_authenticated_html(resp.url, resp.text):
            cookies = login_or_refresh_session(weekly_url, force_interactive=False)
            if cookies:
                session = build_http_session(cookies)
                resp = session.get(weekly_url, allow_redirects=True, timeout=20)

        info = parse_attendance_view(resp.text, resp.url)
        if info["sessions_summary"]:
            return info["sessions_summary"]
    except Exception as e:
        log(f"⚠️ Error fetching weekly view: {e}")

    # Fallback to view=5
    try:
        all_url = f"{base_url}{sep}view=5"
        resp = session.get(all_url, allow_redirects=True, timeout=20)
        info = parse_attendance_view(resp.text, resp.url)
        return info["sessions_summary"][:5]
    except Exception:
        return []


def get_all_weekly_status() -> list[dict]:
    """Aggregates weekly attendance sessions across all configured courses."""
    cfg = load_config()
    results = []
    for c in cfg.get("courses", []):
        name = c.get("name", "Course")
        sessions = fetch_weekly_sessions(c)
        results.append({
            "course": name,
            "url": c["url"],
            "sessions": sessions,
        })
    return results


def get_full_status(force_refresh: bool = False) -> dict:
    """
    Fetches whole-week attendance statistics, weekly schedule, and session history
    for all configured courses.
    Adheres strictly to PROJECT.md § Interface Contracts.
    """
    cfg = load_config()
    courses_cfg = cfg.get("courses", [])

    cookies = load_cookies()
    authenticated = False
    session = None
    if cookies:
        session = build_http_session(cookies)
        try:
            test_resp = session.get(normalize_spectrum_url("https://spectrum.um.edu.my/my/"), allow_redirects=True, timeout=10)
            authenticated = is_authenticated_html(test_resp.url, test_resp.text)
        except Exception:
            authenticated = False

    courses_list = []
    for c in courses_cfg:
        cid = extract_course_id(c)
        cname = c.get("name", f"Course {cid}")
        sched_str = format_schedule_string(c.get("schedule", []))
        url = normalize_spectrum_url(c["url"])

        stats = {
            "taken_sessions": 0,
            "points_achieved": 0,
            "points_total": 0,
            "points_ratio": "0 / 0",
            "attendance_rate": 100.0,
            "percentage_label": "100.0%",
        }
        sessions = []
        has_active = False

        if authenticated and session:
            try:
                sep = "&" if "?" in url else "?"
                weekly_url = f"{url}{sep}view=2"
                resp = session.get(weekly_url, allow_redirects=True, timeout=15)
                if not is_authenticated_html(resp.url, resp.text):
                    resp = session.get(url, allow_redirects=True, timeout=15)

                if is_authenticated_html(resp.url, resp.text):
                    info = parse_attendance_view(resp.text, resp.url, course_id=cid)
                    stats = info.get("stats", stats)
                    sessions = info.get("parsed_sessions", [])
                    has_active = len(info.get("submit_links", [])) > 0
                    if not sessions:
                        # Fallback to base url if weekly view had no sessions
                        resp_base = session.get(url, allow_redirects=True, timeout=15)
                        if is_authenticated_html(resp_base.url, resp_base.text):
                            info_base = parse_attendance_view(resp_base.text, resp_base.url, course_id=cid)
                            stats = info_base.get("stats", stats)
                            sessions = info_base.get("parsed_sessions", [])
                            has_active = has_active or len(info_base.get("submit_links", [])) > 0
            except Exception as e:
                log(f"⚠️ Error fetching status for course {cid}: {e}")

        rate = float(stats.get("attendance_rate", 100.0))
        below_thresh = rate < 80.0

        courses_list.append({
            "course_id": cid,
            "course_name": cname,
            "schedule": sched_str,
            "taken_sessions": stats.get("taken_sessions", 0),
            "points_achieved": stats.get("points_achieved", 0),
            "points_total": stats.get("points_total", 0),
            "attendance_rate": rate,
            "below_threshold": below_thresh,
            "sessions": sessions,
            "stats": stats,
            "url": url,
            "has_active_session": has_active,
        })

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "status": "success",
        "success": True,
        "updated_at": now_iso,
        "authenticated": authenticated,
        "courses": courses_list,
        "pending_password": get_pending_password() or None,
    }


def submit_password(password: str, course_id: str = None) -> tuple[bool, str]:
    """
    Submits a password code to pending attendance session.
    Returns (success: bool, message: str).
    """
    return submit_pending_password(password)


def check_and_submit(course_id: str = None, password: str = None) -> list[dict]:
    """
    Checks and submits attendance for a specified course (or all courses if None).
    Returns list of structured results adhering to PROJECT.md:
      [
        {
          "course_id": "1121957",
          "course_name": "WIA2006 Lecture (DK1)",
          "result": "ALREADY_RECORDED",
          "status": "already_taken_or_closed",
          "message": "Attendance already recorded as Present"
        }
      ]
    """
    cfg = load_config()
    courses = cfg.get("courses", [])
    if course_id:
        target = [c for c in courses if extract_course_id(c) == str(course_id) or c.get("name") == str(course_id)]
        if target:
            courses = target
        else:
            courses = [{
                "name": f"Course {course_id}",
                "url": f"https://spectrum.um.edu.my/mod/attendance/view.php?id={course_id}",
                "status_label": "Present",
            }]

    results = []
    for c in courses:
        res = check_and_submit_course(c, password=password)
        cid = extract_course_id(c)
        cname = c.get("name", res.get("title") or f"Course {cid}")
        status = res.get("status", "error")

        if status == "submitted":
            result_code = "SUBMITTED"
            msg = res.get("message") or "Attendance recorded successfully"
        elif status == "password_required":
            result_code = "PASSWORD_REQUIRED"
            msg = res.get("message") or "Attendance is open and requires a password"
        elif status == "already_taken_or_closed":
            result_code = "ALREADY_RECORDED"
            msg = res.get("message") or "Attendance already recorded as Present"
        elif status == "auth_failed":
            result_code = "AUTH_FAILED"
            msg = res.get("message") or "Authentication failed"
        else:
            result_code = "ERROR"
            msg = res.get("message") or "Error checking attendance"

        results.append({
            "course_id": cid,
            "course_name": cname,
            "result": result_code,
            "status": status,
            "message": msg,
            "sessions": res.get("sessions", []),
            "title": res.get("title", cname),
        })

    return results


def check_and_submit_all(password: str = None) -> list[dict]:
    """Checks and submits attendance for all configured courses."""
    return check_and_submit(course_id=None, password=password)


def authenticate_sso(
    email: str = None,
    password: str = None,
    target_url: str = None,
    force: bool = False,
) -> dict:
    """
    Performs headless Microsoft SSO authentication using UM credentials
    to establish or refresh session cookies in cookies.json.
    """
    cfg = load_config()
    courses = cfg.get("courses", [])
    url = normalize_spectrum_url(target_url or (courses[0]["url"] if courses else "https://spectrum.um.edu.my/my/"))

    log(f"🔐 authenticate_sso called for URL: {url} (email provided: {bool(email)})")

    cookies = login_or_refresh_session(
        url,
        force_interactive=force,
        email=email,
        password=password,
    )

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if cookies and "MoodleSession" in cookies:
        return {
            "status": "success",
            "success": True,
            "authenticated": True,
            "message": "Authenticated successfully with SPeCTRUM",
            "cookies_updated_at": now_iso,
            "requires_mfa": False,
        }
    else:
        return {
            "status": "failed",
            "success": False,
            "authenticated": False,
            "message": "Authentication failed. Could not obtain SPeCTRUM session cookies.",
            "requires_mfa": False,
        }


def main():
    parser = argparse.ArgumentParser(description="UM SPeCTRUM Automated Attendance Taker")
    parser.add_argument("--login", action="store_true", help="Open Chrome to log in via UM Microsoft SSO")
    parser.add_argument("--once", action="store_true", help="Check all configured courses once and exit")
    parser.add_argument("--watch", action="store_true", help="Continuously poll until attendance is opened and submitted")
    parser.add_argument("--status", action="store_true", help="Print weekly attendance sessions for all courses")
    parser.add_argument("--password", type=str, help="Submit password for attendance")
    parser.add_argument("--url", type=str, help="Override attendance URL to check")
    parser.add_argument("--interval", type=int, help="Polling interval in seconds for --watch mode")
    parser.add_argument("--timeout", type=int, help="Watch timeout in minutes")
    args = parser.parse_args()

    cfg = load_config()
    courses = cfg.get("courses", [])
    if args.url:
        courses = [{"name": "CLI Target Course", "url": args.url, "status_label": "Present"}]

    if not courses:
        log("❌ No courses configured in config.json.")
        sys.exit(1)

    if args.login:
        login_or_refresh_session(courses[0]["url"], force_interactive=True)
        for c in courses:
            check_and_submit_course(c, force_interactive_login=False)
        return

    if args.password:
        ok, msg = submit_pending_password(args.password)
        log(f"Password result: {msg}")
        return

    if args.status:
        weekly = get_all_weekly_status()
        telegram_bot.notify_weekly_status(weekly)
        for item in weekly:
            print(f"\n📘 {item['course']}:")
            for s in item["sessions"]:
                print(f"   • {s}")
        return

    if args.watch:
        interval = args.interval or cfg.get("poll_interval_seconds", 60)
        timeout_min = args.timeout or cfg.get("watch_timeout_minutes", 120)
        deadline = time.time() + (timeout_min * 60)

        log(f"👀 Starting Watch Mode (polling every {interval}s, timeout={timeout_min}m)...")
        pending_courses = list(courses)

        while time.time() < deadline and pending_courses:
            still_pending = []
            for c in pending_courses:
                res = check_and_submit_course(c)
                if res["status"] == "submitted":
                    log(f"🎉 Course '{c.get('name')}' attendance completed!")
                elif res["status"] == "password_required":
                    log("⚠️ Attendance is open but waiting for /password from Telegram.")
                else:
                    still_pending.append(c)

            pending_courses = still_pending
            if not pending_courses:
                log("✨ All watched courses completed! Exiting watch mode.")
                return

            time.sleep(interval)
        return

    # Default: --once check
    for c in courses:
        check_and_submit_course(c)


if __name__ == "__main__":
    main()
