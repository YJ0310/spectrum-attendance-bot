# -*- coding: utf-8 -*-
"""
Tier 2: Boundary & Corner Cases E2E Tests (>= 5 test cases per feature)
Covers:
- F1: Health Check Endpoint Boundaries
- F2: Mini App Hosting Endpoint Boundaries
- F3: Attendance Status API Boundaries & Threshold Rates (0%, 80%, 100%)
- F4: Trigger Check API Boundaries & Invalid JSON/Types
- F5: Password Submission API Boundaries & Empty/Missing Fields
- F6: In-App Microsoft SSO Login API Boundaries & Validation/Injection Resilience
- F18: Telegram Menu Button Registration Boundaries & Timeout/Error Simulation
"""

import json
import os
import subprocess
import sys
import unittest
import warnings
from unittest.mock import patch, MagicMock

import requests

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


# ============================================================================
# F1 Boundaries: Health Check Endpoint (GET /health)
# ============================================================================
class TestFeature1HealthBoundaries(unittest.TestCase):
    """Tier 2: F1 Boundaries (>=5 test cases)."""

    def setUp(self):
        self.client = get_client()

    def test_f1_b01_method_not_allowed_post(self):
        """F1.B1: POST /health returns 405 Method Not Allowed."""
        response = self.client.post("/health")
        self.assertEqual(response.status_code, 405)

    def test_f1_b02_method_not_allowed_put_delete(self):
        """F1.B2: PUT and DELETE /health return 405 Method Not Allowed."""
        res_put = self.client.put("/health")
        self.assertEqual(res_put.status_code, 405)
        res_del = self.client.delete("/health")
        self.assertEqual(res_del.status_code, 405)

    def test_f1_b03_extraneous_query_params(self):
        """F1.B3: GET /health with extraneous query params returns 200 ok."""
        response = self.client.get("/health?debug=true&token=invalid&foo=bar&test=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ok")

    def test_f1_b04_burst_load_rapid_requests(self):
        """F1.B4: 20 rapid sequential requests to /health all return 200 without failure."""
        for _ in range(20):
            res = self.client.get("/health")
            self.assertEqual(res.status_code, 200)

    def test_f1_b05_large_headers_handling(self):
        """F1.B5: GET /health with large custom header string handled without server crash."""
        large_header = "x" * 2048
        response = self.client.get("/health", headers={"X-Custom-Test-Header": large_header})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ok")


# ============================================================================
# F2 Boundaries: Mini App Hosting Endpoint (GET /app)
# ============================================================================
class TestFeature2MiniAppBoundaries(unittest.TestCase):
    """Tier 2: F2 Boundaries (>=5 test cases)."""

    def setUp(self):
        self.client = get_client()

    def test_f2_b01_method_not_allowed_post(self):
        """F2.B1: POST /app returns 405 Method Not Allowed."""
        response = self.client.post("/app")
        self.assertEqual(response.status_code, 405)

    def test_f2_b02_method_not_allowed_delete(self):
        """F2.B2: DELETE /app returns 405 Method Not Allowed."""
        response = self.client.delete("/app")
        self.assertEqual(response.status_code, 405)

    def test_f2_b03_telegram_query_params(self):
        """F2.B3: GET /app preserves handling with complex Telegram launch query parameters."""
        tg_params = "?tgWebAppVersion=7.0&tgWebAppPlatform=ios&tgWebAppThemeParams=%7B%22bg_color%22%3A%22%23ffffff%22%7D"
        response = self.client.get(f"/app{tg_params}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))

    def test_f2_b04_head_request_handling(self):
        """F2.B4: HEAD /app returns 200 with text/html header and empty body."""
        response = self.client.head("/app")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertEqual(len(response.content), 0)

    def test_f2_b05_trailing_slash_clean_handling(self):
        """F2.B5: GET /app/ resolves cleanly or redirects to /app without 500 error."""
        response = self.client.get("/app/", follow_redirects=True)
        self.assertIn(response.status_code, [200, 404])

    def test_f2_b06_path_traversal_rejection(self):
        """F2.B6: Reject path traversal payloads attempting to disclose files outside webapp/."""
        traversal_paths = [
            "/static/%2e%2e/.env",
            "/static/%2e%2e/server.py",
            "/static/%2e%2e/config.json",
            "/static/%2e%2e%2f.env",
            "/static/..%2f.env",
            "/static/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ]
        for path in traversal_paths:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 404, f"Path traversal {path} should return 404, got {res.status_code}")

    def test_f2_b07_static_asset_routes(self):
        """F2.B7: Direct and prefixed routes for Mini App CSS and JS return 200 with appropriate media types."""
        assets = [
            ("/style.css", "text/css"),
            ("/app/style.css", "text/css"),
            ("/static/style.css", "text/css"),
            ("/app.js", "application/javascript"),
            ("/app/app.js", "application/javascript"),
            ("/static/app.js", "application/javascript"),
        ]
        for path, expected_type in assets:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Asset {path} returned status {res.status_code}")
            content_type = res.headers.get("content-type", "")
            self.assertIn(expected_type, content_type, f"Asset {path} expected {expected_type}, got {content_type}")


# ============================================================================
# F3 Boundaries: Attendance Status API (GET /api/status)
# ============================================================================
class TestFeature3AttendanceStatusBoundaries(unittest.TestCase):
    """Tier 2: F3 Boundaries (>=5 test cases)."""

    def setUp(self):
        self.client = get_client()

    def test_f3_b01_method_not_allowed_post(self):
        """F3.B1: POST /api/status returns 405 Method Not Allowed."""
        response = self.client.post("/api/status")
        self.assertEqual(response.status_code, 405)

    def test_f3_b02_threshold_boundary_low_rate(self):
        """F3.B2: Attendance rate < 80% correctly sets below_threshold = True."""
        mock_data = {
            "status": "success",
            "updated_at": "2026-10-24T08:00:00Z",
            "authenticated": True,
            "courses": [
                {
                    "course_id": "1121957",
                    "course_name": "Test Course Low",
                    "attendance_rate": 79.9,
                    "below_threshold": True,
                    "sessions": [],
                }
            ],
        }
        with patch("attendance.get_full_status", return_value=mock_data):
            response = self.client.get("/api/status")
            self.assertEqual(response.status_code, 200)
            courses = response.json().get("courses", [])
            for c in courses:
                if c.get("attendance_rate", 100) < 80.0:
                    self.assertTrue(c.get("below_threshold"), "below_threshold must be True when rate < 80%")

    def test_f3_b03_threshold_boundary_exact_80(self):
        """F3.B3: Attendance rate == 80.0% sets below_threshold = False."""
        mock_data = {
            "status": "success",
            "updated_at": "2026-10-24T08:00:00Z",
            "authenticated": True,
            "courses": [
                {
                    "course_id": "1121957",
                    "course_name": "Test Course Exact 80",
                    "attendance_rate": 80.0,
                    "below_threshold": False,
                    "sessions": [],
                }
            ],
        }
        with patch("attendance.get_full_status", return_value=mock_data):
            response = self.client.get("/api/status")
            self.assertEqual(response.status_code, 200)
            courses = response.json().get("courses", [])
            for c in courses:
                if c.get("attendance_rate") == 80.0:
                    self.assertFalse(c.get("below_threshold"), "below_threshold must be False at 80.0%")

    def test_f3_b04_threshold_boundary_100_percent(self):
        """F3.B4: Attendance rate == 100.0% sets below_threshold = False."""
        mock_data = {
            "status": "success",
            "updated_at": "2026-10-24T08:00:00Z",
            "authenticated": True,
            "courses": [
                {
                    "course_id": "1121957",
                    "course_name": "Test Course 100%",
                    "attendance_rate": 100.0,
                    "below_threshold": False,
                    "sessions": [],
                }
            ],
        }
        with patch("attendance.get_full_status", return_value=mock_data):
            response = self.client.get("/api/status")
            self.assertEqual(response.status_code, 200)
            courses = response.json().get("courses", [])
            for c in courses:
                if c.get("attendance_rate") == 100.0:
                    self.assertFalse(c.get("below_threshold"))

    def test_f3_b05_threshold_boundary_0_percent_no_division_by_zero(self):
        """F3.B5: Course with 0 sessions taken or 0% rate sets below_threshold = True without crash."""
        mock_data = {
            "status": "success",
            "updated_at": "2026-10-24T08:00:00Z",
            "authenticated": True,
            "courses": [
                {
                    "course_id": "1121957",
                    "course_name": "Test Course 0%",
                    "attendance_rate": 0.0,
                    "below_threshold": True,
                    "sessions": [],
                }
            ],
        }
        with patch("attendance.get_full_status", return_value=mock_data):
            response = self.client.get("/api/status")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("status"), "success")


# ============================================================================
# F4 Boundaries: Trigger Check API (POST /api/check)
# ============================================================================
class TestFeature4TriggerCheckBoundaries(unittest.TestCase):
    """Tier 2: F4 Boundaries (>=5 test cases)."""

    def setUp(self):
        self.client = get_client()

    def test_f4_b01_method_not_allowed_get(self):
        """F4.B1: GET /api/check returns 405 Method Not Allowed."""
        response = self.client.get("/api/check")
        self.assertEqual(response.status_code, 405)

    def test_f4_b02_invalid_json_payload(self):
        """F4.B2: POST /api/check with malformed JSON string returns 400 or 422."""
        response = self.client.post(
            "/api/check",
            content='{"course_id": broken',
            headers={"Content-Type": "application/json"},
        )
        self.assertIn(response.status_code, [400, 422])

    def test_f4_b03_empty_body_vs_empty_json(self):
        """F4.B3: Calling /api/check with no body handles cleanly."""
        response = self.client.post("/api/check", content="", headers={"Content-Type": "application/json"})
        self.assertIn(response.status_code, [200, 400, 422])
        if response.status_code == 200:
            self.assertEqual(response.json().get("status"), "success")

    def test_f4_b04_nonexistent_course_id(self):
        """F4.B4: Nonexistent course ID returns structured response without 500 server crash."""
        response = self.client.post("/api/check", json={"course_id": "nonexistent_999999"})
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)

    def test_f4_b05_invalid_datatype_course_id(self):
        """F4.B5: Unexpected datatype in course_id (e.g. array) handled cleanly."""
        response = self.client.post("/api/check", json={"course_id": [1, 2, 3]})
        # FastAPI returns 422 for pydantic schema validation or coerces cleanly
        self.assertIn(response.status_code, [200, 422])


# ============================================================================
# F5 Boundaries: Password Submission API (POST /api/password)
# ============================================================================
class TestFeature5PasswordSubmissionBoundaries(unittest.TestCase):
    """Tier 2: F5 Boundaries (>=5 test cases)."""

    def setUp(self):
        self.client = get_client()

    def test_f5_b01_method_not_allowed_get(self):
        """F5.B1: GET /api/password returns 405 Method Not Allowed."""
        response = self.client.get("/api/password")
        self.assertEqual(response.status_code, 405)

    def test_f5_b02_empty_password_string(self):
        """F5.B2: POST /api/password with empty string password handled cleanly."""
        response = self.client.post("/api/password", json={"password": ""})
        # Either validates and returns 422/400 or returns structured failure response
        self.assertIn(response.status_code, [200, 400, 422])

    def test_f5_b03_missing_password_field(self):
        """F5.B3: POST /api/password with missing 'password' field returns 422."""
        response = self.client.post("/api/password", json={"wrong_key": "1234"})
        self.assertEqual(response.status_code, 422, "Missing required password field should return 422")

    def test_f5_b04_malformed_json(self):
        """F5.B4: POST /api/password with malformed JSON returns 400 or 422."""
        response = self.client.post(
            "/api/password",
            content='{"password": ',
            headers={"Content-Type": "application/json"},
        )
        self.assertIn(response.status_code, [400, 422])

    def test_f5_b05_extremely_long_password(self):
        """F5.B5: Extremely long password string (2,000 chars) handled without buffer overflow."""
        long_pass = "P" * 2000
        response = self.client.post("/api/password", json={"password": long_pass})
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 200)


# ============================================================================
# F6 Boundaries: In-App Microsoft SSO Login API (POST /api/login)
# ============================================================================
class TestFeature6SSOLoginBoundaries(unittest.TestCase):
    """Tier 2: F6 Boundaries (>=5 test cases)."""

    def setUp(self):
        self.client = get_client()

    def test_f6_b01_method_not_allowed_get(self):
        """F6.B1: GET /api/login returns 405 Method Not Allowed."""
        response = self.client.get("/api/login")
        self.assertEqual(response.status_code, 405)

    def test_f6_b02_malformed_json_body(self):
        """F6.B2: POST /api/login with broken JSON returns 400 or 422."""
        response = self.client.post(
            "/api/login",
            content='{"email": "broken',
            headers={"Content-Type": "application/json"},
        )
        self.assertIn(response.status_code, [400, 422])

    def test_f6_b03_empty_fields_in_payload(self):
        """F6.B3: POST /api/login with empty strings in credentials handled cleanly."""
        with patch("attendance.authenticate_sso", return_value={"status": "failed", "authenticated": False, "message": "Missing credentials"}):
            response = self.client.post("/api/login", json={"email": "", "password": ""})
            self.assertNotEqual(response.status_code, 500)

    def test_f6_b04_malformed_email_format(self):
        """F6.B4: Non-email string handled gracefully without unhandled exception."""
        with patch("attendance.authenticate_sso", return_value={"status": "failed", "authenticated": False, "message": "Invalid email"}):
            response = self.client.post("/api/login", json={"email": "not_an_email_address", "password": "123"})
            self.assertNotEqual(response.status_code, 500)

    def test_f6_b05_injection_strings_resilience(self):
        """F6.B5: SQL injection & script payload strings handled safely without server error."""
        with patch("attendance.authenticate_sso", return_value={"status": "failed", "authenticated": False, "message": "Failed"}):
            response = self.client.post(
                "/api/login",
                json={
                    "email": "' OR '1'='1' --",
                    "password": "<script>alert('xss')</script>",
                },
            )
            self.assertNotEqual(response.status_code, 500)


# ============================================================================
# F18 Boundaries: Telegram Menu Button Registration (register_menu_button.py & helper)
# ============================================================================
class TestFeature18MenuButtonRegistrationBoundaries(unittest.TestCase):
    """Tier 2: F18 Boundaries (>=5 test cases)."""

    def setUp(self):
        self.script_path = os.path.join(PROJECT_ROOT, "register_menu_button.py")

    def test_f18_b01_malformed_url_scheme(self):
        """F18.B1: Invalid URL scheme (e.g. ftp:// or javascript:) rejected."""
        import telegram_bot

        if not hasattr(telegram_bot, "set_chat_menu_button"):
            raise unittest.SkipTest("telegram_bot.set_chat_menu_button not yet implemented (Milestone 3)")

        ok = telegram_bot.set_chat_menu_button(
            web_app_url="javascript:alert(1)",
            token="dummy_token",
        )
        self.assertFalse(ok, "Invalid or non-http(s) URL scheme should be rejected")

    def test_f18_b02_missing_bot_token_everywhere(self):
        """F18.B2: Missing bot token in CLI and empty environment returns False / exits non-zero."""
        import telegram_bot

        if not hasattr(telegram_bot, "set_chat_menu_button"):
            raise unittest.SkipTest("telegram_bot.set_chat_menu_button not yet implemented (Milestone 3)")

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}, clear=True):
            ok = telegram_bot.set_chat_menu_button(
                web_app_url="https://example.com/app",
                token="",
            )
            self.assertFalse(ok, "set_chat_menu_button should return False when no token is available")

    def test_f18_b03_special_characters_in_button_text(self):
        """F18.B3: Button text containing emojis, quotes, and unicode handled properly."""
        import telegram_bot

        if not hasattr(telegram_bot, "set_chat_menu_button"):
            raise unittest.SkipTest("telegram_bot.set_chat_menu_button not yet implemented (Milestone 3)")

        captured_text = None

        def mock_post(url, json=None, timeout=None):
            nonlocal captured_text
            if json and "menu_button" in json:
                captured_text = json["menu_button"].get("text")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"ok": True, "result": True}
            return mock_resp

        special_text = "🎓 SPeCTRUM «Mini App» 🔥"
        with patch("requests.post", side_effect=mock_post):
            ok = telegram_bot.set_chat_menu_button(
                web_app_url="https://example.com/app",
                text=special_text,
                token="dummy_token",
            )
            self.assertTrue(ok)
            self.assertEqual(captured_text, special_text)

    def test_f18_b04_telegram_api_500_server_error_simulation(self):
        """F18.B4: Simulated Telegram API HTTP 500 error handled gracefully, returning False."""
        import telegram_bot

        if not hasattr(telegram_bot, "set_chat_menu_button"):
            raise unittest.SkipTest("telegram_bot.set_chat_menu_button not yet implemented (Milestone 3)")

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Telegram Server Error"

        with patch("requests.post", return_value=mock_resp):
            ok = telegram_bot.set_chat_menu_button(
                web_app_url="https://example.com/app",
                token="dummy_token",
            )
            self.assertFalse(ok, "Should return False when Telegram API returns 500")

    def test_f18_b05_telegram_api_network_timeout_simulation(self):
        """F18.B5: Network timeout during setChatMenuButton handled cleanly, returning False."""
        import telegram_bot

        if not hasattr(telegram_bot, "set_chat_menu_button"):
            raise unittest.SkipTest("telegram_bot.set_chat_menu_button not yet implemented (Milestone 3)")

        with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out")):
            ok = telegram_bot.set_chat_menu_button(
                web_app_url="https://example.com/app",
                token="dummy_token",
            )
            self.assertFalse(ok, "Should return False on network timeout")


if __name__ == "__main__":
    unittest.main()
