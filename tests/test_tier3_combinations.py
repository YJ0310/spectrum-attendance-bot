# -*- coding: utf-8 -*-
"""
Tier 3: Cross-Feature Combinations (Pairwise Coverage) E2E Tests
Covers:
- TC1: Health check during active status querying (non-blocking async event loop)
- TC2: Login -> Status query -> Check trigger pipeline (state consistency across auth & check)
- TC3: Check attendance returning PASSWORD_REQUIRED -> Password submission -> Status verification
- TC4: Mini App HTML /app & app.js integration with backend REST endpoints
- TC5: Menu button configuration pointing to /app validated against server route
- TC6: Concurrency stress testing across all endpoints simultaneously
"""

import concurrent.futures
import json
import os
import sys
import unittest
import warnings
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

warnings.filterwarnings("ignore", category=DeprecationWarning)


def get_client():
    """Returns a TestClient instance for server.app, or skips if server is unavailable."""
    try:
        import server
        from fastapi.testclient import TestClient
        return TestClient(server.app, raise_server_exceptions=False)
    except (ImportError, AttributeError) as e:
        raise unittest.SkipTest(f"server.app not available: {e}")


class TestTier3Combinations(unittest.TestCase):
    """Tier 3: Cross-Feature Combinations."""

    def setUp(self):
        self.client = get_client()

    def test_tc01_health_during_status_query(self):
        """TC1: Health check /health succeeds without delay while /api/status is being actively queried."""
        results = []

        def call_status():
            res = self.client.get("/api/status")
            results.append(("status", res.status_code))

        def call_health():
            for _ in range(5):
                res = self.client.get("/health")
                results.append(("health", res.status_code))

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            f1 = executor.submit(call_status)
            f2 = executor.submit(call_health)
            concurrent.futures.wait([f1, f2], timeout=15)

        self.assertGreaterEqual(len(results), 6)
        for endpoint, code in results:
            self.assertEqual(code, 200, f"Endpoint {endpoint} failed during concurrent execution")

    def test_tc02_login_then_status_then_check_pipeline(self):
        """TC2: Multi-step pipeline: Login credentials -> Query status -> Trigger attendance check."""
        # 1. Login
        mock_auth = {
            "status": "success",
            "authenticated": True,
            "message": "Authenticated successfully with SPeCTRUM",
        }
        with patch("attendance.authenticate_sso", return_value=mock_auth):
            login_resp = self.client.post(
                "/api/login",
                json={"email": "student@siswa.um.edu.my", "password": "Password123"},
            )
            self.assertEqual(login_resp.status_code, 200)
            self.assertTrue(login_resp.json().get("authenticated"))

        # 2. Query Status
        status_resp = self.client.get("/api/status")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertEqual(status_data.get("status"), "success")
        self.assertIn("courses", status_data)

        # 3. Trigger Check
        check_resp = self.client.post("/api/check", json={"course_id": "1121957"})
        self.assertEqual(check_resp.status_code, 200)
        check_data = check_resp.json()
        self.assertEqual(check_data.get("status"), "success")
        self.assertIn("results", check_data)

    def test_tc03_check_password_required_then_submit_password(self):
        """TC3: Attendance check detects PASSWORD_REQUIRED -> User submits session password -> Session confirmed."""
        # Step 1: Simulate check returning PASSWORD_REQUIRED
        mock_check_results = [
            {
                "course_id": "1121957",
                "course_name": "WIA2006 Lecture (DK1)",
                "result": "PASSWORD_REQUIRED",
                "status": "password_required",
                "message": "Attendance requires password",
            }
        ]
        with patch("attendance.check_and_submit", return_value=mock_check_results):
            check_res = self.client.post("/api/check", json={"course_id": "1121957"})
            self.assertEqual(check_res.status_code, 200)
            data = check_res.json()
            self.assertEqual(data.get("status"), "success")
            self.assertEqual(data["results"][0]["result"], "PASSWORD_REQUIRED")

        # Step 2: Submit password to pending session
        with patch("attendance.submit_password", return_value=(True, "Success: Attendance recorded")):
            pwd_res = self.client.post("/api/password", json={"password": "SECRET_PIN_1234"})
            self.assertEqual(pwd_res.status_code, 200)
            pwd_data = pwd_res.json()
            self.assertEqual(pwd_data.get("status"), "success")
            self.assertEqual(pwd_data.get("result"), "SUBMITTED")

    def test_tc04_miniapp_frontend_backend_api_integration(self):
        """TC4: Mini App frontend HTML and app.js correctly reference backend API routes."""
        app_res = self.client.get("/app")
        self.assertEqual(app_res.status_code, 200)

        # Inspect webapp files
        webapp_dir = os.path.join(PROJECT_ROOT, "webapp")
        app_js_path = os.path.join(webapp_dir, "app.js")
        index_html_path = os.path.join(webapp_dir, "index.html")

        self.assertTrue(os.path.exists(index_html_path), "webapp/index.html must exist")
        self.assertTrue(os.path.exists(app_js_path), "webapp/app.js must exist")

        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js_content = f.read()

        # Verify app.js references all primary backend endpoints
        self.assertIn("/api/status", app_js_content, "app.js must fetch /api/status")
        self.assertIn("/api/check", app_js_content, "app.js must call /api/check")
        self.assertIn("/api/password", app_js_content, "app.js must call /api/password")
        self.assertIn("/api/login", app_js_content, "app.js must call /api/login")

        # Verify static asset HTTP delivery (relative, prefixed, and /static/)
        res_css = self.client.get("/style.css")
        self.assertEqual(res_css.status_code, 200, "GET /style.css must return HTTP 200")
        self.assertIn("text/css", res_css.headers.get("content-type", ""))

        res_js = self.client.get("/app.js")
        self.assertEqual(res_js.status_code, 200, "GET /app.js must return HTTP 200")
        self.assertIn("javascript", res_js.headers.get("content-type", ""))

        res_static_css = self.client.get("/static/style.css")
        self.assertEqual(res_static_css.status_code, 200, "GET /static/style.css must return HTTP 200")

        res_static_js = self.client.get("/static/app.js")
        self.assertEqual(res_static_js.status_code, 200, "GET /static/app.js must return HTTP 200")

        # Verify path traversal protection
        res_traversal = self.client.get("/static/%2e%2e/.env")
        self.assertEqual(res_traversal.status_code, 404, "GET /static/%2e%2e/.env must return 404")


    def test_tc05_menu_button_points_to_valid_app_endpoint(self):
        """TC5: Telegram Menu button URL targets the live /app endpoint served by server."""
        import telegram_bot

        target_url = "https://spectrum-app.onrender.com/app"
        if hasattr(telegram_bot, "set_chat_menu_button"):
            captured = {}

            def mock_post(url, json=None, timeout=None):
                captured.update(json or {})
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"ok": True, "result": True}
                return mock_resp

            with patch("requests.post", side_effect=mock_post):
                telegram_bot.set_chat_menu_button(web_app_url=target_url, token="test_token")
                self.assertEqual(captured["menu_button"]["web_app"]["url"], target_url)

        # Verify that the relative route /app actually serves 200 on server
        app_res = self.client.get("/app")
        self.assertEqual(app_res.status_code, 200)
        self.assertIn("text/html", app_res.headers.get("content-type", ""))

    def test_tc06_concurrency_stress_all_endpoints(self):
        """TC6: Concurrency stress: simultaneous requests across /health, /api/status, /api/check, and /api/password."""
        endpoints = [
            ("GET", "/health", None),
            ("GET", "/api/status", None),
            ("POST", "/api/check", {"course_id": "1121957"}),
            ("POST", "/api/password", {"password": "test"}),
        ]

        def worker(method, path, body):
            if method == "GET":
                return self.client.get(path).status_code
            else:
                return self.client.post(path, json=body).status_code

        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            # Dispatch 4 of each endpoint (16 total concurrent calls)
            for _ in range(4):
                for method, path, body in endpoints:
                    futures.append(executor.submit(worker, method, path, body))

            concurrent.futures.wait(futures, timeout=30)

        status_codes = [f.result() for f in futures]
        self.assertEqual(len(status_codes), 16)
        for code in status_codes:
            self.assertIn(code, [200, 422], f"Unexpected status code {code} during concurrency stress")


if __name__ == "__main__":
    unittest.main()
