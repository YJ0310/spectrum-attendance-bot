#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone CLI utility to register Telegram Bot Menu Button.
Configures @takoo_helper_bot to launch the SPeCTRUM Telegram Mini App.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

import telegram_bot

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Register Telegram Bot Menu Button for SPeCTRUM Mini App."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="URL of the Telegram Mini App (e.g. https://.../app)",
    )
    parser.add_argument(
        "--text",
        default="SPeCTRUM",
        help="Text displayed on the menu button (default: 'SPeCTRUM')",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Telegram Bot Token (defaults to TELEGRAM_BOT_TOKEN from env)",
    )
    parser.add_argument(
        "--chat-id",
        default=None,
        help="Target Chat ID (optional; if omitted, sets global menu button)",
    )

    args = parser.parse_args(argv)

    # Ensure .env is loaded
    load_dotenv(os.path.join(BASE_DIR, ".env"))

    # Resolve token
    token = args.token
    if not token:
        env_token, _ = telegram_bot.get_credentials()
        token = env_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    if not token:
        print(
            "❌ Error: Bot token not provided and not in environment.",
            file=sys.stderr,
        )
        return 1

    chat_desc = args.chat_id if args.chat_id else "(Global for all chats)"
    print("🤖 Configuring Telegram Bot Menu Button...")
    print(f"   URL:     {args.url}")
    print(f"   Text:    {args.text}")
    print(f"   Chat ID: {chat_desc}")

    success = telegram_bot.set_chat_menu_button(
        web_app_url=args.url,
        text=args.text,
        chat_id=args.chat_id,
        token=token,
    )

    if success:
        print("✅ Telegram menu button configured successfully!")
        return 0
    else:
        print(
            "❌ Failed to configure Telegram menu button.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
