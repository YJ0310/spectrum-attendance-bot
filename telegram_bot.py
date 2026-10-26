#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot API integration for UM SPeCTRUM Auto-Attendance.
Communicates with @takoo_helper_bot via official Telegram HTTP APIs.
"""

import html
import os
import sys
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

TELEGRAM_API_BASE = "https://api.telegram.org"


def get_credentials() -> tuple[str, str]:
    """Returns (bot_token, chat_id) from environment or .env."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id


def is_configured() -> bool:
    token, chat_id = get_credentials()
    return bool(token and chat_id)


def send_message(
    text: str,
    chat_id: str = None,
    token: str = None,
    parse_mode: str = "HTML",
    reply_markup: Optional[dict] = None,
) -> bool:
    """
    Sends a message via Telegram Bot API.
    Defaults to HTML parse mode for robust formatting without markdown escaping issues.
    Optionally accepts reply_markup (e.g. InlineKeyboardMarkup) for interactive buttons.
    """
    bot_token, default_chat_id = get_credentials()
    tok = token or bot_token
    cid = chat_id or default_chat_id

    if not tok or not cid:
        return False

    url = f"{TELEGRAM_API_BASE}/bot{tok}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            return True
        # If HTML parse error occurred, retry with plain text
        if "can't parse entities" in resp.text:
            payload.pop("parse_mode", None)
            retry = requests.post(url, json=payload, timeout=15)
            return retry.status_code == 200
        print(f"[Telegram] Failed to send message: {resp.text}")
        return False
    except Exception as e:
        print(f"[Telegram] Error sending message: {e}")
        return False


def send_attendance_reminder(
    course_name: str,
    course_url: str,
    minutes_before: int = 5,
    chat_id: Optional[str] = None,
) -> bool:
    """
    Sends an interactive class attendance reminder with 1-tap inline action buttons.
    Allows user to tap directly and open SPeCTRUM on their phone via domestic/campus connection.
    """
    app_url = os.environ.get("WEBAPP_URL") or "https://spectrum-attendance-bot.onrender.com/app"
    text = (
        f"⏰ <b>SPeCTRUM Attendance Reminder</b>\n\n"
        f"📚 <b>Course:</b> {course_name}\n"
        f"⏳ Class starts in <b>{minutes_before} minutes</b>!\n\n"
        f"👉 Tap the button below to submit your attendance now:"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "⚡ 1-Tap Submit Attendance", "url": course_url}
            ],
            [
                {"text": "📊 Open SPeCTRUM Mini App", "web_app": {"url": app_url}}
            ]
        ]
    }
    return send_message(text, chat_id=chat_id, reply_markup=reply_markup)


def set_chat_menu_button(
    web_app_url: str,
    text: str = "SPeCTRUM",
    chat_id: Optional[str] = None,
    token: Optional[str] = None,
) -> bool:
    """
    Configures Telegram Bot Menu Button to launch a Web App (Mini App).
    Sends POST https://api.telegram.org/bot<token>/setChatMenuButton.

    :param web_app_url: HTTPS (or HTTP) URL to load inside the Mini App.
    :param text: Button title displayed in bottom-left corner.
    :param chat_id: Optional chat ID. If omitted, sets default button.
    :param token: Optional bot token override. Defaults to TELEGRAM_BOT_TOKEN.
    :return: True if successfully registered, False otherwise.
    """
    if not web_app_url or not isinstance(web_app_url, str):
        return False

    clean_url = web_app_url.strip()
    parsed = urlparse(clean_url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return False

    bot_token, default_chat_id = get_credentials()
    tok = (token if token is not None else bot_token).strip()
    if not tok:
        return False

    payload = {
        "menu_button": {
            "type": "web_app",
            "text": text if text is not None else "SPeCTRUM",
            "web_app": {
                "url": clean_url,
            },
        }
    }
    if chat_id is not None and str(chat_id).strip():
        payload["chat_id"] = str(chat_id).strip()

    url = f"{TELEGRAM_API_BASE}/bot{tok}/setChatMenuButton"
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return bool(data.get("ok", False))
        print(
            f"[Telegram] Failed setChatMenuButton ({resp.status_code}): "
            f"{resp.text}"
        )
        return False
    except Exception as e:
        print(f"[Telegram] Error setting chat menu button: {e}")
        return False


def get_chat_menu_button(
    chat_id: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """
    Retrieves the current configuration of the Telegram Bot Menu Button.
    Sends POST https://api.telegram.org/bot<token>/getChatMenuButton.

    :param chat_id: Optional chat ID. If omitted, gets default button.
    :param token: Optional bot token override. Defaults to TELEGRAM_BOT_TOKEN.
    :return: Dict returned in result, or empty dict on failure.
    """
    bot_token, default_chat_id = get_credentials()
    tok = (token if token is not None else bot_token).strip()
    if not tok:
        return {}

    url = f"{TELEGRAM_API_BASE}/bot{tok}/getChatMenuButton"
    payload = {}
    if chat_id is not None and str(chat_id).strip():
        payload["chat_id"] = str(chat_id).strip()

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data.get("result", {})
        return {}
    except Exception as e:
        print(f"[Telegram] Error getting chat menu button: {e}")
        return {}


def notify_attendance_recorded(course_name: str, session_info: str, points: str = ""):
    """Sends a formatted notification when attendance is marked Present."""
    clean_course = html.escape(course_name)
    clean_session = html.escape(session_info)
    clean_points = html.escape(points) if points else "Present"

    msg = (
        f"🎓 <b>SPeCTRUM Attendance Recorded!</b>\n\n"
        f"📚 <b>Course:</b> {clean_course}\n"
        f"✅ <b>Status:</b> Present ({clean_points})\n"
        f"🕒 <b>Session:</b> {clean_session}\n"
        f"⚡ <i>Auto-submitted by SPeCTRUM Bot</i>"
    )
    return send_message(msg)


def notify_password_required(course_name: str, session_info: str):
    """Sends an alert prompting the user to send the session password."""
    clean_course = html.escape(course_name)
    clean_session = html.escape(session_info)

    msg = (
        f"⚠️ <b>Attendance Password Required!</b>\n\n"
        f"📚 <b>Course:</b> {clean_course}\n"
        f"🕒 <b>Session:</b> {clean_session}\n\n"
        f"👉 Reply to this bot with:\n"
        f"<code>/password &lt;code&gt;</code>\n"
        f"<i>(e.g., /password 1234)</i>"
    )
    return send_message(msg)


def notify_weekly_status(weekly_data: list[dict]):
    """Formats and sends the full week's attendance status."""
    if not weekly_data:
        return send_message("📅 <b>SPeCTRUM Weekly Attendance</b>\n\nNo classes found for this week.")

    lines = ["📅 <b>SPeCTRUM Weekly Attendance</b>\n"]
    for item in weekly_data:
        course = html.escape(item.get("course", "Course"))
        sessions = item.get("sessions", [])
        lines.append(f"📚 <b>{course}</b>")
        if not sessions:
            lines.append("  • <i>No sessions scheduled this week.</i>")
        else:
            for s in sessions:
                icon = "✅" if "present" in s.lower() or "hadir" in s.lower() else "⏳"
                lines.append(f"  {icon} {html.escape(s)}")
        lines.append("")

    return send_message("\n".join(lines).strip())


def get_bot_info(token: str) -> dict:
    """Queries /getMe to check token validity and retrieve bot metadata."""
    try:
        resp = requests.get(f"{TELEGRAM_API_BASE}/bot{token}/getMe", timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data["result"]
    except Exception:
        pass
    return {}


def setup_wizard():
    """Interactive CLI wizard to configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""
    print("=" * 60)
    print("🤖 Telegram Bot Setup Wizard (@takoo_helper_bot)")
    print("=" * 60)

    token = input("Enter your Telegram Bot Token (from @BotFather): ").strip()
    if not token:
        print("❌ Token cannot be empty.")
        return

    print("🔍 Verifying token with Telegram API...")
    info = get_bot_info(token)
    if not info:
        print("❌ Invalid bot token. Please check and try again.")
        return

    bot_username = info.get("username", "unknown_bot")
    print(f"✅ Connected to @{bot_username} ({info.get('first_name', '')})")

    print("\n📬 Now let's detect your Telegram Chat ID.")
    print(f"👉 Please open Telegram, search for @{bot_username}, and send: /start")
    print("⏳ Waiting for your message (timeout 60s)...")

    detected_chat_id = None
    first_name = ""
    for _ in range(30):
        time.sleep(2)
        try:
            r = requests.get(f"{TELEGRAM_API_BASE}/bot{token}/getUpdates", timeout=10).json()
            if r.get("ok") and r.get("result"):
                for update in reversed(r["result"]):
                    msg = update.get("message", {})
                    chat = msg.get("chat", {})
                    if chat.get("id"):
                        detected_chat_id = str(chat["id"])
                        first_name = chat.get("first_name", "")
                        break
            if detected_chat_id:
                break
        except Exception:
            pass

    if not detected_chat_id:
        detected_chat_id = input("\nCould not automatically detect message. Please enter your Chat ID manually: ").strip()

    if not detected_chat_id:
        print("❌ Chat ID is required.")
        return

    print(f"🎉 Detected Chat ID: {detected_chat_id} ({first_name})")

    # Send a confirmation test message
    test_msg = "👋 <b>Hello!</b> Your SPeCTRUM Auto-Attendance Bot is now linked successfully."
    ok = send_message(test_msg, chat_id=detected_chat_id, token=token)
    if ok:
        print("✅ Test message delivered to your Telegram!")
    else:
        print("⚠️ Test message could not be sent. Check your chat ID.")

    # Write to .env
    existing_lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("TELEGRAM_BOT_TOKEN=") and not line.startswith("TELEGRAM_CHAT_ID="):
                    existing_lines.append(line)

    existing_lines.append(f"TELEGRAM_BOT_TOKEN={token}\n")
    existing_lines.append(f"TELEGRAM_CHAT_ID={detected_chat_id}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)

    print(f"💾 Saved configuration to {ENV_FILE}")
    print("✨ Setup complete!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        setup_wizard()
    elif len(sys.argv) > 1 and sys.argv[1] == "--test":
        tok, cid = get_credentials()
        if not tok or not cid:
            print("❌ Telegram credentials not found in .env. Run with --setup first.")
            sys.exit(1)
        ok = send_message("🧪 <b>SPeCTRUM Test Notification</b>: Telegram connection working!")
        print("Message sent:", ok)
    else:
        tok, cid = get_credentials()
        print(f"Telegram Configured: {is_configured()}")
        if tok:
            print(f"Token: {tok[:10]}... (len {len(tok)})")
        if cid:
            print(f"Chat ID: {cid}")
