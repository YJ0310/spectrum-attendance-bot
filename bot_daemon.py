#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
24/7 Cloud Daemon for SPeCTRUM Auto-Attendance & Telegram Bot (@takoo_helper_bot).
Handles two-way Telegram commands:
  /check           - Immediately checks SPeCTRUM and takes attendance if open
  /status          - Displays all attendance sessions for the whole week
  /password <code> - Submits password to active attendance session
  /help            - Displays command menu
Also includes an autonomous background timer to poll during class times.
"""

import asyncio
import html
import os
import threading
import time
from datetime import datetime

import httpx
import requests
from dotenv import load_dotenv

import attendance
import telegram_bot

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def handle_check_command(chat_id: str):
    """Handles the /check command by checking all courses immediately."""
    telegram_bot.send_message("🔍 <i>Checking SPeCTRUM attendance now...</i>", chat_id=chat_id)
    results = attendance.check_and_submit_all()

    lines = ["📊 <b>SPeCTRUM Attendance Check:</b>\n"]
    for r in results:
        status = r.get("status")
        title = r.get("title") or r.get("course", "Course")
        msg = r.get("message", "")

        if status == "submitted":
            lines.append(f"✅ <b>{html.escape(title)}</b>\n  • Marked 'Present' successfully!")
        elif status == "password_required":
            lines.append(
                f"⚠️ <b>{html.escape(title)}</b>\n"
                f"  • Attendance is open and requires a password!\n"
                f"  • Send <code>/password &lt;code&gt;</code> to submit."
            )
        elif status == "already_taken_or_closed":
            sessions = r.get("sessions", [])
            latest = sessions[0] if sessions else "No sessions open."
            lines.append(f"⏸️ <b>{html.escape(title)}</b>\n  • No active session to submit.\n  • Latest: <i>{html.escape(latest)}</i>")
        else:
            lines.append(f"ℹ️ <b>{html.escape(title)}</b>: {html.escape(msg)}")
        lines.append("")

    telegram_bot.send_message("\n".join(lines).strip(), chat_id=chat_id)


def handle_status_command(chat_id: str):
    """Handles the /status command by fetching whole-week attendance sessions."""
    telegram_bot.send_message("📅 <i>Fetching whole week attendance sessions...</i>", chat_id=chat_id)
    weekly_data = attendance.get_all_weekly_status()

    lines = ["📅 <b>SPeCTRUM Weekly Attendance</b>\n"]
    for item in weekly_data:
        course = html.escape(item.get("course", "Course"))
        sessions = item.get("sessions", [])
        lines.append(f"📚 <b>{course}</b>")
        if not sessions:
            lines.append("  • <i>No sessions found for this week.</i>")
        else:
            for s in sessions:
                icon = "✅" if "present" in s.lower() or "hadir" in s.lower() else "⏳"
                lines.append(f"  {icon} {html.escape(s)}")
        lines.append("")

    telegram_bot.send_message("\n".join(lines).strip(), chat_id=chat_id)


def handle_password_command(chat_id: str, text: str):
    """Handles /password <code> or /pass <code>."""
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        telegram_bot.send_message(
            "⚠️ Please provide the password code.\nUsage: <code>/password 1234</code>",
            chat_id=chat_id,
        )
        return

    code = parts[1].strip()
    telegram_bot.send_message(f"🔑 <i>Submitting password '{html.escape(code)}' to SPeCTRUM...</i>", chat_id=chat_id)

    ok, msg = attendance.submit_pending_password(code)
    if ok:
        telegram_bot.send_message(f"🎉 <b>Success:</b> {html.escape(msg)}", chat_id=chat_id)
    else:
        telegram_bot.send_message(f"❌ <b>Submission Failed:</b> {html.escape(msg)}", chat_id=chat_id)


def handle_help_command(chat_id: str):
    msg = (
        "🤖 <b>SPeCTRUM Auto-Attendance Bot Menu</b>\n\n"
        "/check - Check attendance now & auto-submit if open\n"
        "/status - View all attendance sessions for this week\n"
        "/password &lt;code&gt; - Submit password for active session\n"
        "/help - Show this help menu\n\n"
        "⚡ <i>Running 24/7 on Cloud Tracker</i>"
    )
    telegram_bot.send_message(msg, chat_id=chat_id)


def run_background_scheduler():
    """Autonomous background thread checking class attendance during scheduled hours."""
    attendance.log("⏱️ Background class watcher thread started.")
    while True:
        try:
            cfg = attendance.load_config()
            now = datetime.now()
            current_weekday = now.strftime("%a")  # e.g. Thu
            current_hour = now.hour

            for course in cfg.get("courses", []):
                for sched in course.get("schedule", []):
                    s_day = str(sched.get("day", "")).lower()
                    s_hour = int(sched.get("hour", -1))
                    # If within class window (scheduled hour, or 1 hour after)
                    if s_day.startswith(current_weekday.lower()[:3]) and current_hour in (s_hour, s_hour + 1):
                        attendance.log(f"⏰ Active class window for {course.get('name')}. Checking attendance...")
                        attendance.check_and_submit_course(course)
        except Exception as e:
            attendance.log(f"⚠️ Scheduler error: {e}")

        # Sleep 60 seconds between checks
        time.sleep(60)


def run_telegram_listener():
    """Long-polls Telegram Bot API for incoming user commands."""
    token, default_chat_id = telegram_bot.get_credentials()
    if not token:
        attendance.log("❌ TELEGRAM_BOT_TOKEN not configured in .env. Run `python3 telegram_bot.py --setup` first.")
        return

    attendance.log("🤖 Starting 24/7 Telegram Bot listener...")
    offset = 0

    # Start background class watcher thread
    t = threading.Thread(target=run_background_scheduler, daemon=True)
    t.start()

    while True:
        try:
            url = f"{telegram_bot.TELEGRAM_API_BASE}/bot{token}/getUpdates"
            params = {"offset": offset, "timeout": 25}
            resp = requests.get(url, params=params, timeout=30)

            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            if not data.get("ok"):
                time.sleep(3)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))
                text = msg.get("text", "").strip()

                if not text or not chat_id:
                    continue

                attendance.log(f"📩 Telegram command received from {chat_id}: '{text}'")

                cmd = text.split()[0].lower()
                if cmd in ("/check", "/check@takoo_helper_bot"):
                    handle_check_command(chat_id)
                elif cmd in ("/status", "/status@takoo_helper_bot"):
                    handle_status_command(chat_id)
                elif cmd in ("/password", "/pass", "/password@takoo_helper_bot"):
                    handle_password_command(chat_id, text)
                elif cmd in ("/help", "/start"):
                    handle_help_command(chat_id)

        except requests.exceptions.RequestException:
            time.sleep(3)
        except Exception as e:
            attendance.log(f"⚠️ Error in Telegram listener loop: {e}")
            time.sleep(2)


async def run_async_class_watcher(stop_event: asyncio.Event):
    """
    Autonomous async background task checking class attendance during scheduled hours.
    Cooperative shutdown via stop_event.
    """
    attendance.log("⏰ Async class-time watcher started.")
    while not stop_event.is_set():
        try:
            cfg = attendance.load_config()
            now = datetime.now()
            current_weekday = now.strftime("%a")
            current_hour = now.hour

            for course in cfg.get("courses", []):
                for sched in course.get("schedule", []):
                    s_day = str(sched.get("day", "")).lower()
                    s_hour = int(sched.get("hour", -1))
                    if s_day.startswith(current_weekday.lower()[:3]) and current_hour in (s_hour, s_hour + 1):
                        attendance.log(f"⏰ Active class window for {course.get('name')}. Checking attendance...")
                        await asyncio.to_thread(attendance.check_and_submit_course, course)
        except asyncio.CancelledError:
            break
        except Exception as e:
            attendance.log(f"⚠️ Async class watcher error: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60.0)
        except (asyncio.TimeoutError, TimeoutError):
            pass


async def run_async_telegram_listener(stop_event: asyncio.Event):
    """
    Non-blocking async long-polling listener using httpx for Telegram Bot updates.
    Cooperative shutdown via stop_event.
    Dispatches long-running tasks to threads to keep event loop responsive.
    """
    token, default_chat_id = telegram_bot.get_credentials()
    if not token:
        attendance.log("⚠️ TELEGRAM_BOT_TOKEN not configured; Telegram listener not started.")
        return

    attendance.log("🤖 Starting async Telegram Bot listener (httpx)...")
    offset = 0

    async with httpx.AsyncClient(timeout=35.0) as client:
        while not stop_event.is_set():
            try:
                url = f"{telegram_bot.TELEGRAM_API_BASE}/bot{token}/getUpdates"
                params = {"offset": offset, "timeout": 25}
                resp = await client.get(url, params=params)

                if resp.status_code == 409:
                    attendance.log("⚠️ Telegram Bot conflict (409 Conflict): another polling instance active. Backing off 10s...")
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=10.0)
                    except (asyncio.TimeoutError, TimeoutError):
                        pass
                    continue

                if resp.status_code != 200:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=3.0)
                    except (asyncio.TimeoutError, TimeoutError):
                        pass
                    continue

                data = resp.json()
                if not data.get("ok"):
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    chat = msg.get("chat", {})
                    chat_id = str(chat.get("id", ""))
                    text = msg.get("text", "").strip()

                    if not text or not chat_id:
                        continue

                    attendance.log(f"📩 Telegram command received from {chat_id}: '{text}'")

                    cmd = text.split()[0].lower()
                    if cmd in ("/check", "/check@takoo_helper_bot"):
                        asyncio.create_task(asyncio.to_thread(handle_check_command, chat_id))
                    elif cmd in ("/status", "/status@takoo_helper_bot"):
                        asyncio.create_task(asyncio.to_thread(handle_status_command, chat_id))
                    elif cmd in ("/password", "/pass", "/password@takoo_helper_bot"):
                        asyncio.create_task(asyncio.to_thread(handle_password_command, chat_id, text))
                    elif cmd in ("/help", "/start"):
                        asyncio.create_task(asyncio.to_thread(handle_help_command, chat_id))
            except httpx.RequestError:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=3.0)
                except (asyncio.TimeoutError, TimeoutError):
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                attendance.log(f"⚠️ Error in async Telegram listener: {e}")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=2.0)
                except (asyncio.TimeoutError, TimeoutError):
                    pass


if __name__ == "__main__":
    run_telegram_listener()
