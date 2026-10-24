#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macOS launchd Background Scheduler for UM SPeCTRUM Auto-Attendance.
Installs, checks status, or removes the background agent at:
  ~/Library/LaunchAgents/com.um.spectrum.attendance.plist
"""

import argparse
import json
import os
import plistlib
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ATTENDANCE_SCRIPT = os.path.join(BASE_DIR, "attendance.py")
STATE_DIR = os.path.expanduser("~/.config/spectrum")
LOG_FILE = os.path.join(STATE_DIR, "attendance.log")

LABEL = "com.um.spectrum.attendance"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")

WEEKDAY_MAP = {
    "sun": 0, "sunday": 0,
    "mon": 1, "monday": 1,
    "tue": 2, "tuesday": 2,
    "wed": 3, "wednesday": 3,
    "thu": 4, "thursday": 4,
    "fri": 5, "friday": 5,
    "sat": 6, "saturday": 6,
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_calendar_intervals(cfg: dict) -> list[dict]:
    """
    Converts course schedules like:
      {"day": "Thu", "hour": 16, "minute": 0}
    into launchd StartCalendarInterval entries.
    """
    intervals = []
    for course in cfg.get("courses", []):
        for sched in course.get("schedule", []):
            day_raw = sched.get("day")
            entry = {}
            if isinstance(day_raw, int):
                entry["Weekday"] = day_raw
            elif isinstance(day_raw, str) and day_raw.strip().lower() in WEEKDAY_MAP:
                entry["Weekday"] = WEEKDAY_MAP[day_raw.strip().lower()]

            if "hour" in sched:
                entry["Hour"] = int(sched["hour"])
            if "minute" in sched:
                entry["Minute"] = int(sched["minute"])
            else:
                entry["Minute"] = 0

            if entry:
                intervals.append(entry)
    return intervals


def install_agent(interval_seconds: int = None, watch_mode: bool = False):
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)

    cfg = load_config()
    cal_intervals = build_calendar_intervals(cfg)

    python_bin = sys.executable
    cmd_args = [python_bin, ATTENDANCE_SCRIPT, "--watch" if (watch_mode or cal_intervals) else "--once"]

    plist_data = {
        "Label": LABEL,
        "ProgramArguments": cmd_args,
        "WorkingDirectory": BASE_DIR,
        "StandardOutPath": LOG_FILE,
        "StandardErrorPath": LOG_FILE,
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
        },
    }

    if cal_intervals and not interval_seconds:
        plist_data["StartCalendarInterval"] = cal_intervals
        mode_desc = f"scheduled class times ({len(cal_intervals)} slot(s)) in --watch mode"
    else:
        every_sec = interval_seconds or 300
        plist_data["StartInterval"] = every_sec
        plist_data["RunAtLoad"] = True
        mode_desc = f"every {every_sec} seconds"

    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist_data, f)

    subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
    res = subprocess.run(["launchctl", "load", PLIST_PATH], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"✅ Installed and loaded launchd agent: {PLIST_PATH}")
        print(f"⏱️  Schedule: {mode_desc}")
        print(f"📄 Logs: {LOG_FILE}")
    else:
        print(f"❌ Failed to load launchd agent: {res.stderr.strip()}")


def uninstall_agent():
    if os.path.exists(PLIST_PATH):
        subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
        os.remove(PLIST_PATH)
        print(f"🗑️  Uninstalled and removed {PLIST_PATH}")
    else:
        print(f"ℹ️  No launchd agent installed at {PLIST_PATH}")


def status_agent():
    res = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    lines = [line for line in res.stdout.splitlines() if LABEL in line]
    if lines:
        print(f"🟢 Background agent '{LABEL}' is ACTIVE:")
        for l in lines:
            print(f"   {l}")
    else:
        print(f"⚪ Background agent '{LABEL}' is NOT loaded.")

    if os.path.exists(LOG_FILE):
        print(f"\n📄 Last 15 lines of {LOG_FILE}:")
        print("-" * 60)
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            tail = f.readlines()[-15:]
            for line in tail:
                print(line.rstrip())
        print("-" * 60)


def main():
    parser = argparse.ArgumentParser(description="Manage macOS launchd background scheduler for SPeCTRUM Attendance")
    sub = parser.add_subparsers(dest="action", required=True)

    p_install = sub.add_parser("install", help="Install and start the background launchd service")
    p_install.add_argument(
        "--every",
        type=int,
        default=None,
        help="Check every N seconds (default: uses schedule in config.json, or every 300s if no schedule set)",
    )
    p_install.add_argument(
        "--watch",
        action="store_true",
        help="Use --watch mode when triggered",
    )

    sub.add_parser("uninstall", help="Stop and remove the background launchd service")
    sub.add_parser("status", help="Check service status and view recent logs")

    args = parser.parse_args()
    if args.action == "install":
        install_agent(interval_seconds=args.every, watch_mode=args.watch)
    elif args.action == "uninstall":
        uninstall_agent()
    elif args.action == "status":
        status_agent()


if __name__ == "__main__":
    main()
