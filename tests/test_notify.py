"""P1 Slack notification: message content, escaping, and that it never costs the work note. No real HTTP calls."""
import json
import unittest
from unittest import mock

from jarvis.main import handle
from jarvis.notify import slack_message
from tests.test_jarvis import INCIDENTS, FakeLLM, FakeSnow

NOTE = "[Jarvis] Resolution suggestion\n\nProbable cause: VPN ports blocked\nSources: KB0010016\nConfidence: high"
WEBHOOK = {"NOTIFY_WEBHOOK_URL": "https://hooks.slack.test/x"}


class TestNotify(unittest.TestCase):
    def test_message_has_link_cause_and_escapes_ticket_text(self):
        inc = {"sys_id": "abc", "number": "INC9", "short_description": "VPN down <!channel> & co", "description": "<@U123>"}
        msg = json.dumps(slack_message(inc, NOTE, "https://dev1.service-now.com"))
        self.assertIn("https://dev1.service-now.com/incident.do?sys_id=abc", msg)
        self.assertIn("VPN ports blocked", msg)
        self.assertIn("KB0010016", msg)
        self.assertNotIn("<!channel>", msg)   # no mass mention from user text
        self.assertNotIn("<@U123>", msg)
        self.assertIn("&lt;!channel&gt; &amp; co", msg)

    def run_handle(self, priority, post):
        snow = FakeSnow()
        snow.instance = "https://dev1.service-now.com"
        inc = {"sys_id": "abc", "number": "INC9", "priority": priority, **INCIDENTS["open"][0]}
        with mock.patch.dict("os.environ", WEBHOOK), mock.patch("jarvis.notify.requests.post", post):
            handle(inc, snow, FakeLLM(), "test-model")
        return snow

    def test_only_p1_is_sent(self):
        post = mock.Mock()
        self.run_handle("1", post)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], WEBHOOK["NOTIFY_WEBHOOK_URL"])
        post.reset_mock()
        self.run_handle("3", post)
        post.assert_not_called()

    def test_slack_failure_keeps_the_work_note(self):
        snow = self.run_handle("1", mock.Mock(side_effect=ConnectionError("slack down")))
        self.assertIn("abc", snow.notes)

    def test_disabled_without_webhook(self):
        post = mock.Mock()
        with mock.patch.dict("os.environ", {"NOTIFY_WEBHOOK_URL": ""}), mock.patch("jarvis.notify.requests.post", post):
            snow = FakeSnow()
            snow.instance = "x"
            handle({"sys_id": "abc", "number": "INC9", "priority": "1", **INCIDENTS["open"][0]}, snow, FakeLLM(), "m")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
