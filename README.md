# 🎓 SPeCTRUM Auto-Attendance & Telegram Bot (@takoo_helper_bot)

24/7 Cloud-ready Automated Attendance Tracker for Universiti Malaya's **SPeCTRUM** (`spectrum.um.edu.my`), featuring two-way Telegram control via `@takoo_helper_bot`, silent Microsoft SSO re-authentication, whole-week schedule inspection, and `/password <code>` submission.

---

## 📱 Telegram Commands (`@takoo_helper_bot`)

| Command | Action |
| :--- | :--- |
| **`/check`** | Immediately scrapes SPeCTRUM, checks active attendance sessions, and auto-submits **`Present`**. |
| **`/status`** | Fetches and displays the **whole week's attendance sessions** (dates, times, status, points, remarks). |
| **`/password <code>`** | If a session requires a password, submit it directly via Telegram (e.g., `/password 1234`). |
| **`/help`** | Displays the command menu and tracker status. |

---

## 🚀 Quick Setup: Linking `@takoo_helper_bot`

1. Open Telegram, start `@BotFather`, and copy your bot token for `@takoo_helper_bot`.
2. Run the interactive setup wizard:
   ```bash
   python3 telegram_bot.py --setup
   ```
   - Paste your bot token.
   - Send `/start` to `@takoo_helper_bot` in Telegram.
   - The wizard will automatically capture your `chat_id`, test sending a message, and write them to `.env`.

Alternatively, fill in `.env` directly:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_telegram_chat_id
UM_EMAIL=your_student_id@siswa.um.edu.my
UM_PASSWORD=your_password
```

---

## ☁️ 24/7 Cloud Deployment (No Mac Required)

You can run this 24/7 on any cheap or free Linux cloud server (AWS EC2 free tier, Oracle Cloud Always Free, DigitalOcean, or Railway).

### Option A: Docker Compose (Recommended)

1. Clone this repository to your server:
   ```bash
   git clone https://github.com/YJ0310/spectrum.git
   cd spectrum
   ```
2. Configure your `.env` (or run `python3 telegram_bot.py --setup`).
3. Start the bot:
   ```bash
   docker compose up -d --build
   ```
4. View real-time logs:
   ```bash
   docker compose logs -f
   ```

The bot runs 24/7 in the container, listens to your Telegram commands, and checks attendance automatically during scheduled class windows.

---

### Option B: Linux VPS via systemd

1. Install Chromium and Python dependencies on your server:
   ```bash
   sudo apt update && sudo apt install -y python3-pip chromium chromium-driver
   pip3 install -r requirements.txt
   ```
2. Copy the service file:
   ```bash
   sudo cp spectrum-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now spectrum-bot
   ```
3. Check status:
   ```bash
   sudo systemctl status spectrum-bot
   ```

---

## 💻 Running Locally (Mac / PC)

- **Start 24/7 Telegram Listener locally**:
  ```bash
  python3 bot_daemon.py
  ```
- **Manual Attendance Check**:
  ```bash
  python3 attendance.py --once
  ```
- **View Whole Week Status**:
  ```bash
  python3 attendance.py --status
  ```
- **Class Watch Mode**:
  ```bash
  python3 attendance.py --watch
  ```
