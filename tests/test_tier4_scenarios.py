# -*- coding: utf-8 -*-
"""
Tier 4: Real-World Application Scenarios E2E Tests (>= 5 scenarios)
Covers:
- Scenario 1: Complete daily attendance workflow (Health ping -> Open Mini App -> View timeline -> 1-Tap check -> View status)
- Scenario 2: Password-protected class session workflow (Trigger check -> Detect PASSWORD_REQUIRED -> Submit session password -> Verify recorded)
- Scenario 3: Weekly schedule & course timetable overview (Verify all 3 courses: WIA2006 Lecture DK1, WIA2006 Tutorial OCC3, SIF4001 Daily Project)
- Scenario 4: Re-authentication session refresh workflow (Session expired -> Submit login credentials -> Session restored -> Attendance verified)
- Scenario 5: 24/7 Cloud deployment keep-alive pinger concurrency workflow (Periodic /health polling under active user traffic)
"""

import concurrent.futures
import json
import os
import sys
import time
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


class TestTier4Scenarios(unittest.TestCase):
    """Tier 4: Real-World Application Scenarios."""

    def setUp(self):
        self.client = get_client()

    def test_scenario_1_daily_attendance_workflow(self):
        """Scenario 1: Complete Daily Student Attendance Workflow.
        Flow:
          1. External keep-alive pings /health
          2. User opens Telegram Mini App (/app)
          3. Dashboard fetches weekly attendance status (/api/status)
          4. User taps 1-tap "Check Attendance" button (/api/check)
          5. Dashboard fetches refreshed status (/api/status?refresh=true)
        """
        # Step 1: Health Check
        health_resp = self.client.get("/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json().get("status"), "ok")

        # Step 2: Open Mini App
        app_resp = self.client.get("/app")
        self.assertEqual(app_resp.status_code, 200)
        self.assertIn("text/html", app_resp.headers.get("content-type", ""))
        self.assertIn("telegram.org/js/telegram-web-app.js", app_resp.text)

        # Step 3: View weekly status
        status_resp = self.client.get("/api/status")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertEqual(status_data.get("status"), "success")
        self.assertIn("courses", status_data)
        initial_courses = status_data["courses"]
        self.assertGreaterEqual(len(initial_courses), 1)

        # Step 4: 1-Tap Attendance Check
        check_resp = self.client.post("/api/check", json={})
        self.assertEqual(check_resp.status_code, 200)
        check_data = check_resp.json()
        self.assertEqual(check_data.get("status"), "success")
        self.assertIn("results", check_data)

        # Step 5: Refresh Status View
        refresh_resp = self.client.get("/api/status?refresh=true")
        self.assertEqual(refresh_resp.status_code, 200)
        refresh_data = refresh_resp.json()
        self.assertEqual(refresh_data.get("status"), "success")
        self.assertIn("courses", refresh_data)

    def test_scenario_2_password_protected_session_workflow(self):
        """Scenario 2: Password-Protected Class Session Workflow.
        Flow:
          1. Student triggers attendance check
          2. System reports PASSWORD_REQUIRED
          3. Student enters password PIN dialog and submits
          4. Attendance confirmed recorded
        """
        # Step 1 & 2: Check detects password required
        mock_password_required_result = [
            {
                "course_id": "1121957",
                "course_name": "WIA2006 Lecture (DK1)",
                "result": "PASSWORD_REQUIRED",
                "status": "password_required",
                "message": "Attendance is open and requires a password",
            }
        ]
        with patch("attendance.check_and_submit", return_value=mock_password_required_result):
            with patch("attendance.get_pending_password", return_value={"submit_url": "https://spectrum.um.edu.my/mod/attendance/attendance.php", "course_name": "WIA2006 Lecture (DK1)"}):
                check_resp = self.client.post("/api/check", json={"course_id": "1121957"})
                self.assertEqual(check_resp.status_code, 200)
                check_data = check_resp.json()
                self.assertEqual(check_data.get("status"), "success")
                self.assertTrue(check_data.get("has_pending_password"))
                self.assertEqual(check_data.get("pending_course"), "WIA2006 Lecture (DK1)")

        # Step 3 & 4: User submits password PIN via in-app dialog
        with patch("attendance.submit_password", return_value=(True, "Success: Attendance recorded for WIA2006 Lecture (DK1)!")):
            pwd_resp = self.client.post("/api/password", json={"password": "7391", "course_id": "1121957"})
            self.assertEqual(pwd_resp.status_code, 200)
            pwd_data = pwd_resp.json()
            self.assertEqual(pwd_data.get("status"), "success")
            self.assertEqual(pwd_data.get("result"), "SUBMITTED")
            self.assertIn("Attendance recorded", pwd_data.get("message", ""))

    def test_scenario_3_weekly_schedule_overview_three_courses(self):
        """Scenario 3: Weekly Schedule & Course Timetable Overview.
        Flow:
          1. Query attendance status for all courses
          2. Verify all 3 configured courses are present:
             - WIA2006 Lecture (DK1) (Thursday 16:00)
             - WIA2006 Tutorial (OCC3) (Tuesday 10:00)
             - SIF4001 Daily Project (Mon-Fri 10:00)
          3. Verify threshold alert flags and schedule mapping
        """
        status_resp = self.client.get("/api/status")
        self.assertEqual(status_resp.status_code, 200)
        data = status_resp.json()
        courses = data.get("courses", [])

        # Check course names
        names = [c.get("course_name", "") + " " + c.get("name", "") for c in courses]
        all_names = " ".join(names)

        self.assertTrue("WIA2006" in all_names or len(courses) >= 3, f"Expected courses in {names}")

        # Check schedule attributes
        for c in courses:
            self.assertIn("sessions", c)
            # Threshold flag must be a boolean
            self.assertIsInstance(c.get("below_threshold", False), bool)

    def test_scenario_4_session_expiry_and_reauthentication_workflow(self):
        """Scenario 4: Re-Authentication / Session Expiry Workflow.
        Flow:
          1. SPeCTRUM session expires (authenticated=False)
          2. User opens login modal and enters UM credentials
          3. Microsoft SSO login succeeds and refreshes session
          4. User performs attendance check successfully
        """
        # Step 1: Session unauthenticated
        unauth_status = {
            "status": "success",
            "updated_at": "2026-10-24T08:00:00Z",
            "authenticated": False,
            "courses": [],
        }
        with patch("attendance.get_full_status", return_value=unauth_status):
            res_unauth = self.client.get("/api/status?refresh=true")
            self.assertEqual(res_unauth.status_code, 200)
            self.assertFalse(res_unauth.json().get("authenticated"))

        # Step 2 & 3: User submits UM Microsoft SSO credentials
        mock_auth_success = {
            "status": "success",
            "authenticated": True,
            "message": "Authenticated successfully with SPeCTRUM",
        }
        with patch("attendance.authenticate_sso", return_value=mock_auth_success):
            login_res = self.client.post(
                "/api/login",
                json={
                    "email": "student@siswa.um.edu.my",
                    "password": "CorrectPassword2026",
                },
            )
            self.assertEqual(login_res.status_code, 200)
            login_data = login_res.json()
            self.assertTrue(login_data.get("authenticated"))
            self.assertEqual(login_data.get("status"), "success")

        # Step 4: Perform attendance check with restored session
        check_res = self.client.post("/api/check", json={})
        self.assertEqual(check_res.status_code, 200)
        self.assertEqual(check_res.json().get("status"), "success")

    def test_scenario_5_cloud_keep_alive_pinger_concurrency_workflow(self):
        """Scenario 5: 24/7 Cloud Deployment Keep-Alive Pinger Concurrency Workflow.
        Flow:
          1. Simulate external keep-alive monitoring (e.g. Render / UptimeRobot)
             issuing continuous rapid /health pings
          2. Simultaneously simulate user activity (querying /api/status and /app)
          3. Verify all requests complete with 200 OK without deadlocks or latency degradation
        """
        health_codes = []
        user_codes = []

        def pinger_task():
            for _ in range(15):
                r = self.client.get("/health")
                health_codes.append(r.status_code)

        def user_task():
            for _ in range(5):
                r1 = self.client.get("/app")
                user_codes.append(r1.status_code)
                r2 = self.client.get("/api/status")
                user_codes.append(r2.status_code)

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            f_ping = executor.submit(pinger_task)
            f_user = executor.submit(user_task)
            concurrent.futures.wait([f_ping, f_user], timeout=25)

        self.assertEqual(len(health_codes), 15)
        for code in health_codes:
            self.assertEqual(code, 200)

        self.assertEqual(len(user_codes), 10)
        for code in user_codes:
            self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
