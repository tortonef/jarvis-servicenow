"""ECC queue bridge to the MID Server and the AD lockout diagnostic. ServiceNow and the MID are faked."""
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from jarvis import mid
from jarvis.main import handle_diagnose, lockout_note

# Trimmed from a real input record written by the helios-mid MID Server
REAL_INPUT = ('<?xml version="1.0" encoding="UTF-8"?><results probe_time="44" result_code="0"><result>'
              '<output>{"account":"nobody.here","found":false}</output></result><parameters>'
              '<parameter name="name" value="Jarvis: lockout_status"/></parameters></results>')
LOCKED = {"account": "alex.rivera", "found": True, "locked": True, "locked_since": "2026-11-07T12:13:31.792Z",
          "unlocks_at": "2026-11-07T12:43:31.792Z", "bad_password_count": 5, "lockout_threshold": 5, "disabled": False}


class FakeSnow:
    executions = None

    def __init__(self, answers_after=1):
        self.created, self.notes, self.audited, self.polls, self.answers_after = [], {}, [], 0, answers_after

    def create(self, table, data):
        self.created.append((table, data))
        return {"sys_id": "out1"}

    def first(self, table, query):
        self.polls += 1
        return {"payload": REAL_INPUT} if self.polls >= self.answers_after else None

    def get_user(self, sys_id):
        return {"user_name": "alex.rivera"} if sys_id == "u1" else None

    def add_work_note(self, sys_id, note, fields=None):
        self.notes[sys_id] = note

    def audit(self, ticket, kind, sources=(), detail=None):
        self.audited.append((ticket, kind))


class TestMid(unittest.TestCase):
    def test_payload_carries_parameters_as_escaped_data(self):
        xml = mid.payload("lockout_status", {"account": 'x"/><parameter name="script" value="evil'})
        params = {p.get("name"): p.get("value") for p in ET.fromstring(xml)}
        self.assertEqual(params["script"], mid.CALLS["lockout_status"])  # injected script parameter did not win
        self.assertEqual(params["account"], 'x"/><parameter name="script" value="evil')

    def test_only_known_calls_reach_the_mid(self):
        with self.assertRaises(ValueError):
            mid.run(FakeSnow(), "rm_rf", {})

    def test_run_writes_output_record_and_reads_the_answer(self):
        snow = FakeSnow(answers_after=2)
        self.assertEqual(mid.run(snow, "lockout_status", {"account": "nobody.here"}, poll=0),
                         {"account": "nobody.here", "found": False})
        table, rec = snow.created[0]
        self.assertEqual((table, rec["topic"], rec["queue"], rec["agent"]),
                         ("ecc_queue", "JavascriptProbe", "output", "mid.server.helios-mid"))

    def test_timeout_and_probe_errors(self):
        with self.assertRaises(TimeoutError):
            mid.run(FakeSnow(answers_after=10**9), "lockout_status", {"account": "a"}, timeout=0.01, poll=0)
        with self.assertRaises(RuntimeError):
            mid.parse_result('<results error="MID not validated"/>')
        with self.assertRaises(RuntimeError):
            mid.parse_result("<results><result><output></output></result></results>")

    def test_lockout_note_variants(self):
        self.assertIn("LOCKED OUT since 12:13 UTC after 5 bad passwords", lockout_note(LOCKED))
        self.assertIn("unlocks automatically at 12:43 UTC", lockout_note(LOCKED))
        self.assertIn("not locked out", lockout_note(dict(LOCKED, locked=False, bad_password_count=0)))
        self.assertIn("not found", lockout_note({"account": "x", "found": False}))
        self.assertIn("check failed: invalid account name", lockout_note({"error": "invalid account name"}))
        self.assertIn("DISABLED", lockout_note(dict(LOCKED, disabled=True)))

    def test_diagnose_uses_the_caller_and_audits(self):
        snow = FakeSnow()
        with mock.patch("jarvis.mid.run", return_value=LOCKED) as run:
            handle_diagnose({"sys_id": "i1", "number": "INC1", "caller_id": {"value": "u1"}}, snow)
        run.assert_called_once_with(snow, "lockout_status", {"account": "alex.rivera"})
        self.assertIn("LOCKED OUT", snow.notes["i1"])
        self.assertEqual(snow.audited, [("INC1", "diagnostic")])
        with mock.patch("jarvis.mid.run") as run:
            handle_diagnose({"sys_id": "i2", "number": "INC2", "caller_id": ""}, snow)
        run.assert_not_called()
        self.assertIn("no valid caller", snow.notes["i2"])


if __name__ == "__main__":
    unittest.main()
