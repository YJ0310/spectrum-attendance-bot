import unittest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup

import telegram_bot
import attendance
import bot_daemon


class TestSystemImprovements(unittest.TestCase):

    def test_send_attendance_reminder_inline_keyboard(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            res = telegram_bot.send_attendance_reminder(
                course_name="SIF4001 Daily Project",
                course_url="https://spectrum.um.edu.my/mod/attendance/view.php?id=1120381",
                minutes_before=5,
                chat_id="1124934036"
            )
            self.assertTrue(res)
            self.assertTrue(mock_post.called)
            sent_payload = mock_post.call_args[1]["json"]
            self.assertIn("reply_markup", sent_payload)
            inline_kb = sent_payload["reply_markup"]["inline_keyboard"]
            self.assertEqual(inline_kb[0][0]["text"], "⚡ 1-Tap Submit Attendance")
            self.assertEqual(inline_kb[0][0]["url"], "https://spectrum.um.edu.my/mod/attendance/view.php?id=1120381")

    def test_quickform_and_query_param_payload_injection(self):
        html = """
        <form action="attendance.php" method="post">
          <input type="radio" name="status" value="272224" id="r1">
          <label for="r1">Present</label>
        </form>
        """
        mock_resp = MagicMock()
        mock_resp.url = "https://spectrum.um.edu.my/mod/attendance/attendance.php"
        mock_resp.text = html

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session.post.return_value = MagicMock(status_code=200, text="Attendance recorded")

        with patch.object(attendance, "clear_pending_password"):
            success, msg = attendance.submit_attendance_form(
                mock_session,
                "https://spectrum.um.edu.my/mod/attendance/attendance.php?sessid=796634&sesskey=cOp1lRKgHp"
            )
            self.assertTrue(success)
            post_call = mock_session.post.call_args[1]["data"]
            self.assertEqual(post_call["sessid"], "796634")
            self.assertEqual(post_call["sesskey"], "cOp1lRKgHp")
            self.assertEqual(post_call["_qf__mod_attendance_form_studentattendance"], "1")
            self.assertEqual(post_call["mform_isexpanded_id_session"], "1")
            self.assertEqual(post_call["status"], "272224")
            self.assertEqual(post_call["submitbutton"], "Save changes")

    def test_calendar_upcoming_view_fetch(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"data": {"events": [{"name": "Lecture 1", "timestart": 1700000000}]}}]

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        events = attendance.fetch_upcoming_calendar_events(mock_session, "dummy_sesskey")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "Lecture 1")


if __name__ == "__main__":
    unittest.main()
