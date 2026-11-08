"""Phase 5: agent feedback, the read-only dashboard login, knowledge gaps as pull requests."""
import datetime
import json
import os
import re
import unittest
from unittest import mock

from jarvis import docs_pr
from jarvis.knowledge import check, parse
from jarvis.main import handle_feedback
from jarvis.snow import Snow
from tests.test_db import URL
from tests.test_jarvis import FakeLLM, FakeSnow

INC = {"sys_id": "abc", "number": "INC0010042", "short_description": "Zoom screen sharing shows a black screen",
       "category": "software", "description": "", "close_notes": "Disabled hardware acceleration."}
DRAFT = {"title": "Zoom: black screen when sharing", "symptom": "Others see black\n## Injected",
         "cause": "GPU acceleration", "steps": ["Open Zoom settings", "Disable hardware\n---\nacceleration"]}


class TestFeedback(unittest.TestCase):
    def latest(self, notes):
        snow = Snow.__new__(Snow)
        snow.query = lambda *a, **k: notes
        return snow.latest_feedback("abc")

    def test_vote_and_author_come_from_the_note(self):
        self.assertEqual(self.latest([{"value": "Jarvis feedback: not helpful (Ann).", "sys_created_by": "ann"}]),
                         ("ann", False))
        self.assertEqual(self.latest([{"value": "Jarvis feedback: helpful (Bob).", "sys_created_by": "bob"}]),
                         ("bob", True))
        self.assertIsNone(self.latest([{"value": "Jarvis feedback: maybe", "sys_created_by": "x"}]))
        self.assertIsNone(self.latest([]))

    def test_no_note_records_nothing(self):
        snow = mock.Mock(db=object())
        snow.latest_feedback.return_value = None
        with mock.patch("jarvis.db.record_feedback") as rec:
            handle_feedback(INC, snow)
        rec.assert_not_called()


class TestDocsPr(unittest.TestCase):
    def test_article_passes_the_ci_check_and_flattens_model_output(self):
        path, text = docs_pr.article(INC, DRAFT, today=datetime.date(2026, 11, 8))
        self.assertEqual(path, "knowledge/articles/zoom-black-screen-when-sharing-inc0010042.md")
        doc = parse(path.removeprefix("knowledge/"), text)
        self.assertEqual(check([doc]), [])
        self.assertEqual((doc["id"], doc["review_by"]), ("KB-INC0010042-001", datetime.date(2027, 5, 7)))
        self.assertEqual(len(re.findall(r"(?m)^## ", doc["body"])), 3)  # Symptom, Cause, Resolution: the injected heading is inline
        self.assertIn("2. Disable hardware --- acceleration", doc["body"])

    def test_open_pr_branch_commit_pull_request(self):
        calls = []

        def request(method, url, **kw):
            calls.append((method, url.split("/repos/o/r")[1]))
            body = {"/git/ref/heads/main": {"object": {"sha": "s1"}}, "/pulls": {"html_url": "https://pr/1"}}
            return mock.Mock(status_code=201, json=lambda: body.get(calls[-1][1], {}), raise_for_status=lambda: None)

        with mock.patch("requests.Session.request", side_effect=request):
            self.assertEqual(docs_pr.open_pr("o/r", "t", INC, "T", "knowledge/articles/a.md", "x"), "https://pr/1")
        self.assertEqual([c[0] for c in calls], ["GET", "POST", "PUT", "POST"])
        self.assertEqual(calls[2][1], "/contents/knowledge/articles/a.md")

    def test_existing_branch_means_already_proposed(self):
        def request(method, url, **kw):
            if url.endswith("/git/refs"):
                return mock.Mock(status_code=422)
            return mock.Mock(status_code=200, json=lambda: {"object": {"sha": "s1"}}, raise_for_status=lambda: None)

        with mock.patch("requests.Session.request", side_effect=request):
            self.assertIsNone(docs_pr.open_pr("o/r", "t", INC, "T", "p", "x"))

    def test_resolved_incident_opens_a_pull_request_with_a_token(self):
        from jarvis.main import handle_resolved
        snow, llm = FakeSnow(), FakeLLM(json.dumps({"covered_by": None, **DRAFT}))
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t", "DOCS_REPO": "o/r"}), \
                mock.patch.object(docs_pr, "open_pr", return_value="https://pr/7") as pr:
            handle_resolved(INC, snow, llm, "m")
        self.assertEqual(pr.call_args.args[:3], ("o/r", "t", INC))
        self.assertEqual(snow.created, [])  # no ServiceNow draft when the PR path is on
        self.assertIn("https://pr/7", snow.notes["abc"])
        self.assertEqual(snow.audited, [("INC0010042", "kb_draft", ["https://pr/7"])])


@unittest.skipUnless(URL, "set TEST_DATABASE_URL to run the database tests")
class TestFeedbackDb(unittest.TestCase):
    def test_vote_upserts_and_reader_cannot_write(self):
        import psycopg
        from jarvis.db import connect, ensure_reader, record_feedback
        conn = connect(URL)
        inc = {"number": "INC-T5", "sys_id": "t5"}
        record_feedback(conn, inc, "ann", False)
        record_feedback(conn, inc, "ann", True)  # changed her mind: one row, latest vote
        self.assertEqual(conn.execute("SELECT helpful FROM feedback WHERE incident_sys_id = 't5'").fetchall(), [(True,)])
        ensure_reader(conn, "reader-test-pw", role="t5_reader")
        ensure_reader(conn, "reader-test-pw", role="t5_reader")  # idempotent
        info = conn.info
        with psycopg.connect(host=info.host, port=info.port, dbname=info.dbname, user="t5_reader",
                             password="reader-test-pw", autocommit=True) as ro:
            self.assertEqual(ro.execute("SELECT count(*) FROM feedback WHERE incident_sys_id = 't5'").fetchone(), (1,))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                ro.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM feedback WHERE incident_sys_id = 't5'")
