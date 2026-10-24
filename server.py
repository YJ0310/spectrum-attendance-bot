#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UM SPeCTRUM Automated Attendance Cloud Web Server & REST API.
Unified FastAPI application hosting:
  - Keep-alive health check for 24/7 cloud hosting (GET /health)
  - Telegram Mini App host (GET /app)
  - RESTful Attendance APIs:
      - GET /api/status   (Weekly sessions, points, attendance rate, threshold alerts)
      - POST /api/check   (1-tap attendance check & 'Present' submission)
      - POST /api/password (Session password submission)
      - POST /api/login   (Headless Microsoft SSO authentication)
  - Concurrency guards: non-blocking threadpool offloading & Chromium mutex lock
  - Async Lifespan daemons: background Telegram Bot long-polling & scheduled class watcher
"""

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

import attendance
import bot_daemon
import telegram_bot

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")


# ---------------------------------------------------------------------------
# Pydantic v2 Schemas (Interface Contracts)
# ---------------------------------------------------------------------------

class CheckPayload(BaseModel):
    course_id: Optional[str] = None
    password: Optional[str] = None


class PasswordPayload(BaseModel):
    password: str = Field(..., min_length=1, description="Attendance password code")
    course_id: Optional[str] = None


class LoginPayload(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    cookies: Optional[dict] = None
    save_credentials: bool = True
    force: bool = False


# ---------------------------------------------------------------------------
# FastAPI Lifespan Handler
# ---------------------------------------------------------------------------

async def run_keep_alive_pinger(stop_event: asyncio.Event):
    """Pings external Render URL every 10 minutes to prevent free tier spin-down."""
    import urllib.request
    external_url = os.environ.get("RENDER_EXTERNAL_URL", "https://spectrum-attendance-bot.onrender.com").rstrip("/")
    health_url = f"{external_url}/health"
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=600)
            break
        except asyncio.TimeoutError:
            try:
                await asyncio.to_thread(urllib.request.urlopen, health_url, timeout=10)
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages startup and cooperative shutdown of background tasks:
      1. Initializes shared concurrency lock for Chromium.
      2. Spawns non-blocking Telegram Bot polling daemon (httpx).
      3. Spawns scheduled class-time watcher.
      4. Spawns external keep-alive pinger.
    """
    app.state.start_time = time.time()
    app.state.selenium_lock = asyncio.Lock()
    app.state.status_lock = asyncio.Lock()
    stop_event = asyncio.Event()
    app.state.stop_event = stop_event
    app.state.status_cache = {"data": None, "timestamp": 0.0}

    bot_task = None
    watcher_task = None
    pinger_task = None

    # Spawn async Telegram listener if configured and not explicitly disabled
    if os.environ.get("ENABLE_BOT_DAEMON", "1").lower() not in ("0", "false"):
        if telegram_bot.is_configured():
            bot_task = asyncio.create_task(bot_daemon.run_async_telegram_listener(stop_event))
            attendance.log("🤖 Lifespan: Async Telegram Bot polling daemon spawned.")
        else:
            attendance.log("ℹ️ Lifespan: Telegram Bot not configured; skipping listener.")

    # Spawn async class-time watcher
    if os.environ.get("ENABLE_CLASS_WATCHER", "1").lower() not in ("0", "false"):
        watcher_task = asyncio.create_task(bot_daemon.run_async_class_watcher(stop_event))
        attendance.log("⏰ Lifespan: Async class-time watcher spawned.")

    if os.environ.get("ENABLE_KEEP_ALIVE", "1").lower() not in ("0", "false"):
        pinger_task = asyncio.create_task(run_keep_alive_pinger(stop_event))

    yield

    # Shutdown sequence
    attendance.log("🛑 Lifespan: Initiating cooperative background worker shutdown...")
    stop_event.set()

    tasks_to_cancel = [t for t in (bot_task, watcher_task, pinger_task) if t is not None]
    for task in tasks_to_cancel:
        task.cancel()

    for task in tasks_to_cancel:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            attendance.log(f"⚠️ Lifespan task shutdown notice: {e}")

    attendance.log("✅ Lifespan: All background workers terminated cleanly.")


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SPeCTRUM Attendance Cloud Service",
    description="24/7 Cloud Automated SPeCTRUM Attendance & Telegram Mini App Backend",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for TMA & external clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helper to invalidate cached status
def invalidate_status_cache():
    if hasattr(app.state, "status_cache"):
        app.state.status_cache = {"data": None, "timestamp": 0.0}


_lock_dict_guard = threading.Lock()


def get_loop_bound_lock(attr_name: str) -> asyncio.Lock:
    """
    Retrieves or creates an asyncio.Lock bound to the current running event loop.
    Prevents 'bound to a different event loop' errors when testing across multi-threaded clients,
    while guaranteeing full coroutine mutual exclusion on any given event loop.
    """
    try:
        curr_loop = asyncio.get_running_loop()
    except RuntimeError:
        curr_loop = None

    with _lock_dict_guard:
        by_loop = getattr(app.state, f"_{attr_name}_by_loop", None)
        if by_loop is None:
            by_loop = {}
            setattr(app.state, f"_{attr_name}_by_loop", by_loop)

        if curr_loop not in by_loop:
            by_loop[curr_loop] = asyncio.Lock()

        # Keep app.state.<attr_name> updated for callers checking state directly
        setattr(app.state, attr_name, by_loop[curr_loop])
        return by_loop[curr_loop]



# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Root redirect to Telegram Mini App or service status."""
    return {
        "status": "ok",
        "service": "SPeCTRUM Attendance Service",
        "app_url": "/app",
        "health_url": "/health",
        "api_status_url": "/api/status",
    }


@app.get("/health")
async def health_check(full: bool = False):
    """
    Keep-alive health check endpoint for external pingers (Render / UptimeRobot).
    Returns exact HTTP 200 {"status": "ok"} as specified by PROJECT.md.
    """
    if full:
        uptime = time.time() - getattr(app.state, "start_time", time.time())
        cookies = attendance.load_cookies()
        has_cookies = bool(cookies and "MoodleSession" in cookies)
        bot_status = "running" if telegram_bot.is_configured() else "not_configured"
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "status": "ok",
            "timestamp": now_iso,
            "uptime_seconds": round(uptime, 2),
            "services": {
                "spectrum_session": "valid" if has_cookies else "unauthenticated",
                "telegram_bot": bot_status,
                "scheduler": "running",
            },
            "version": "1.0.0",
        }
    return {"status": "ok"}


@app.api_route("/app", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/app/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def get_mini_app(request: Request):
    """
    Serves the Telegram Mini App dashboard HTML.
    Supports GET and HEAD methods with Cache-Control: no-cache.
    """
    index_file = os.path.join(WEBAPP_DIR, "index.html")
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    if request.method == "HEAD":
        return Response(content=b"", status_code=200, media_type="text/html; charset=utf-8", headers=headers)

    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html", headers=headers)

    # Fallback placeholder HTML if webapp/index.html is being prepared
    fallback_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPeCTRUM Attendance</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               padding: 20px; background: #0f172a; color: #f8fafc; }
        .card { background: #1e293b; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); }
    </style>
</head>
<body>
    <div class="card">
        <h2>⚡ SPeCTRUM Attendance Mini App</h2>
        <p>Loading dashboard interface...</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=fallback_html, status_code=200, headers=headers)


@app.get("/style.css")
@app.get("/app/style.css")
async def serve_style():
    """Serves the Mini App CSS stylesheet directly for relative and absolute paths."""
    full_path = os.path.join(WEBAPP_DIR, "style.css")
    if os.path.isfile(full_path):
        return FileResponse(full_path, media_type="text/css")
    raise HTTPException(status_code=404, detail="style.css not found")


@app.get("/app.js")
@app.get("/app/app.js")
async def serve_app_js():
    """Serves the Mini App JavaScript application directly for relative and absolute paths."""
    full_path = os.path.join(WEBAPP_DIR, "app.js")
    if os.path.isfile(full_path):
        return FileResponse(full_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")


@app.get("/static/{file_path:path}")
async def serve_static_file(file_path: str):
    """
    Serves static assets (CSS, JS, icons) for the Telegram Mini App.
    Enforces strict canonical path verification to prevent path traversal attacks.
    """
    if ".." in file_path or "%2e" in file_path.lower():
        raise HTTPException(status_code=404, detail=f"Static file '{file_path}' not found")

    real_webapp = os.path.realpath(WEBAPP_DIR)
    real_webapp_prefix = real_webapp if real_webapp.endswith(os.sep) else real_webapp + os.sep

    resolved_path = os.path.realpath(os.path.abspath(os.path.join(WEBAPP_DIR, file_path)))

    if not (resolved_path == real_webapp or resolved_path.startswith(real_webapp_prefix)):
        raise HTTPException(status_code=404, detail=f"Static file '{file_path}' not found")

    if not os.path.isfile(resolved_path):
        raise HTTPException(status_code=404, detail=f"Static file '{file_path}' not found")

    media_type = None
    if resolved_path.endswith(".css"):
        media_type = "text/css"
    elif resolved_path.endswith(".js"):
        media_type = "application/javascript"
    elif resolved_path.endswith(".html"):
        media_type = "text/html"

    return FileResponse(resolved_path, media_type=media_type)


@app.get("/api/status")
async def get_attendance_status(refresh: bool = False):
    """
    Returns structured JSON listing weekly sessions, points, attendance rate,
    and threshold alerts for configured courses.
    Includes 60-second in-memory caching and a mutex lock to prevent cache stampedes (thundering herd).
    """
    now = time.time()
    cache = getattr(app.state, "status_cache", {"data": None, "timestamp": 0.0})

    if not refresh and cache.get("data") and (now - cache.get("timestamp", 0.0) < 60.0):
        cached_data = dict(cache["data"])
        cached_data["cached"] = True
        return cached_data

    status_lock: asyncio.Lock = get_loop_bound_lock("status_lock")

    async with status_lock:
        now = time.time()
        cache = getattr(app.state, "status_cache", {"data": None, "timestamp": 0.0})
        if not refresh and cache.get("data") and (now - cache.get("timestamp", 0.0) < 60.0):
            cached_data = dict(cache["data"])
            cached_data["cached"] = True
            return cached_data

        # Offload blocking HTTP scraping calls to threadpool
        status_data = await asyncio.to_thread(attendance.get_full_status, force_refresh=refresh)
        status_data["cached"] = False

        app.state.status_cache = {"data": status_data, "timestamp": now}
        return status_data


@app.post("/api/check")
async def trigger_attendance_check(payload: Optional[CheckPayload] = None):
    """
    Triggers attendance check and 'Present' submission for configured courses.
    Protected by app.state.selenium_lock to prevent Chromium profile collision
    in the event of session re-authentication.
    """
    cid = payload.course_id if payload else None
    pwd = payload.password if payload else None

    invalidate_status_cache()

    selenium_lock: asyncio.Lock = get_loop_bound_lock("selenium_lock")

    try:
        async with selenium_lock:
            results = await asyncio.to_thread(attendance.check_and_submit, course_id=cid, password=pwd)
    except Exception as e:
        attendance.log(f"⚠️ Error executing /api/check: {e}")
        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "success": False,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "message": f"Error executing attendance check: {str(e)}",
                "results": [],
                "has_pending_password": False,
                "pending_course": None,
            },
        )

    pending = attendance.get_pending_password()
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "status": "success",
        "success": True,
        "timestamp": now_iso,
        "message": "Attendance check completed.",
        "results": results,
        "has_pending_password": bool(pending and pending.get("submit_url")),
        "pending_course": pending.get("course_name") if pending else None,
    }


@app.post("/api/password")
async def submit_session_password(payload: PasswordPayload):
    """
    Submits attendance session password to pending SPeCTRUM form.
    Validates payload and offloads to threadpool.
    """
    if not payload.password or not payload.password.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password cannot be empty.",
        )

    invalidate_status_cache()

    ok, msg = await asyncio.to_thread(
        attendance.submit_password,
        payload.password.strip(),
        course_id=payload.course_id,
    )

    if ok:
        return {
            "status": "success",
            "success": True,
            "message": msg or "Password submitted successfully",
            "result": "SUBMITTED",
        }
    else:
        result_code = "NO_PENDING_SESSION" if "no active" in msg.lower() else "REJECTED"
        return {
            "status": "success" if result_code == "NO_PENDING_SESSION" else "error",
            "success": False,
            "message": msg,
            "result": result_code,
        }


@app.post("/api/login")
async def login_microsoft_sso(payload: Optional[LoginPayload] = None):
    """
    Triggers headless Microsoft SSO authentication using UM credentials
    to establish or refresh session cookies in cookies.json.
    Protected by asyncio.Lock to prevent concurrent browser runs on memory-constrained hosts.
    """
    req_payload = payload or LoginPayload()

    if req_payload.cookies:
        attendance.save_cookies(req_payload.cookies)
        invalidate_status_cache()
        return {
            "status": "success",
            "success": True,
            "authenticated": True,
            "message": "Session cookies synced to cloud server.",
        }

    # Guard: avoid concurrent Chrome processes on 512MB RAM
    selenium_lock: asyncio.Lock = get_loop_bound_lock("selenium_lock")
    if selenium_lock and selenium_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Authentication is currently in progress. Please wait for the current session to finish.",
        )

    invalidate_status_cache()

    async def _do_auth():
        return await asyncio.to_thread(
            attendance.authenticate_sso,
            email=req_payload.email,
            password=req_payload.password,
            force=req_payload.force,
        )

    if selenium_lock:
        async with selenium_lock:
            auth_res = await _do_auth()
    else:
        auth_res = await _do_auth()

    return auth_res


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("server:app", host=host, port=port, reload=False)
