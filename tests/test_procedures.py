"""Procedure catalog, policy and the L1 approval flow. ServiceNow, the LLM and the MID Server are faked."""
import copy
import unittest
from unittest import mock

from jarvis import procedures
from jarvis.main import handle, handle_approve
from tests.test_jarvis import FakeLLM

CATALOG = procedures.load()
LOCKED = {"account": "alex.rivera", "found": True, "locked": True, "bad_password_count": 5}
UNLOCKED = dict(LOCKED, locked=False, bad_password_count=0)
TICKET = {"sys_id": "i1", "number": "INC1", "short_description": "Can't sign in to my laptop",
          "description": "Windows says my account is locked out.", "caller_id": {"value": "u1"}}
DISK = {"sys_id": "i2", "number": "INC2", "short_description": "APP01 log volume almost full",
        "description": "Monitoring: /var/log/helios-portal at 90% on app01."}


class FakeExecutions:
    def __init__(self):
        self.rows = []

    def record_auto(self, incident, pid, params, result):
        self.rows.append({"procedure_id": pid, "status": "auto", "params": params, "result": result})

    def propose(self, incident, pid, risk, params):
        for r in self.rows:
            if r["status"] == "proposed":
                r["status"] = "superseded"
        self.rows.append({"id": 1 + sum(1 for r in self.rows if r.get("id")), "procedure_id": pid, "status": "proposed",
                          "params": params})

    def pending(self, sys_id):
        found = [r for r in self.rows if r["status"] == "proposed"]
        return dict(found[-1]) if found else None

    def finish(self, eid, status, approved_by=None, result=None, verify_result=None):
        row = next(r for r in self.rows if r.get("id") == eid)
        row.update(status=status, approved_by=approved_by, result=result, verify_result=verify_result)


class FakeSnow:
    instance = "https://dev1"
    semantic = knowledge = None

    def __init__(self, docs, approver="jane.agent", user_name="alex.rivera"):
        self.docs, self.approver, self.user_name = docs, approver, user_name
        self.executions, self.notes, self.fields, self.audited = FakeExecutions(), [], [], []

    def search_kb(self, text):
        return [{"number": d, "doc_id": d, "short_description": d, "text": d} for d in self.docs]

    def similar_resolved(self, text):
        return []

    def triage_options(self):
        return {"inquiry": "Inquiry"}, {}

    def get_user(self, sys_id):
        return {"user_name": self.user_name}

    def approval_for_proposal(self, sys_id):
        return self.approver

    def add_work_note(self, sys_id, note, fields=None):
        self.notes.append(note)
        self.fields.append(fields)

    def audit(self, *args, **kwargs):
        self.audited.append(args)


def proposal_row(snow):
    """The L1 proposal row (L0 checks run during approval are logged as rows too)."""
    return next(r for r in snow.executions.rows if r.get("id"))


def mid_returning(*answers):
    """Fake mid.run that answers each call in order and records (call, params)."""
    calls, queue = [], list(answers)
    def run(snow, call, params, **kw):
        calls.append((call, params))
        return queue.pop(0)
    return run, calls


class TestCatalog(unittest.TestCase):
    def test_repository_catalog_is_valid(self):
        self.assertEqual(procedures.check(CATALOG), [])

    def test_check_rejects_unsafe_entries(self):
        bad = copy.deepcopy(CATALOG)
        bad["ad_unlock_account"]["risk"] = "L9"
        bad["portal_health"]["mid"]["call"] = "shell"
        bad["linux_disk_usage"]["params"]["host"] = {"from": "ticket"}             # no enum or pattern
        del bad["linux_clean_logs"]["verify"]
        bad["ad_unlock_account"]["propose_if"]["check"] = "linux_clean_logs"      # not an L0 check
        errors = "\n".join(procedures.check(bad))
        for expected in ("risk must be one of", "mid.call must be one of", "needs a pattern or an enum",
                         "L1 and L2 procedures need propose_if and verify", "propose_if.check must name an L0 procedure"):
            self.assertIn(expected, errors)

    def test_parameters_come_from_data_not_from_free_text(self):
        disk = CATALOG["linux_disk_usage"]
        self.assertEqual(procedures.resolve(disk, DISK, None), {"host": "app01"})
        both = dict(DISK, description="app01 and app02 are both full")
        self.assertIsNone(procedures.resolve(disk, both, None))                    # ambiguous: no guess
        self.assertIsNone(procedures.resolve(disk, dict(DISK, short_description="", description="dc01 full"), None))
        lock = CATALOG["ad_lockout_status"]
        self.assertEqual(procedures.resolve(lock, TICKET, {"user_name": "alex.rivera"}), {"account": "alex.rivera"})
        self.assertIsNone(procedures.resolve(lock, TICKET, {"user_name": "x)(objectClass=*"}))
        self.assertIsNone(procedures.resolve(lock, TICKET, None))

    def test_rules(self):
        self.assertTrue(procedures.holds({"field": "use_percent", "at_least": 80}, {"use_percent": 84}))
        self.assertFalse(procedures.holds({"field": "use_percent", "at_least": 80}, {"use_percent": 3}))
        self.assertFalse(procedures.holds({"field": "use_percent", "at_least": 80}, {}))
        self.assertFalse(procedures.holds({"field": "locked", "equals": True}, {"error": "MID down", "locked": True}))


class TestFlow(unittest.TestCase):
    def test_locked_caller_gets_diagnosis_and_unlock_proposal(self):
        snow = FakeSnow(["KB-IAM-001"])
        run, calls = mid_returning(LOCKED)
        with mock.patch("jarvis.mid.run", run):
            handle(dict(TICKET), snow, FakeLLM(), "m")
        self.assertEqual(calls, [("lockout_status", {"account": "alex.rivera"})])
        self.assertIn("Diagnostics (read only", snow.notes[0])
        self.assertIn("locked True", snow.notes[0])
        self.assertTrue(snow.notes[1].startswith("[Jarvis] Proposed procedure (L1, needs your approval): Unlock"))
        self.assertEqual(snow.executions.pending("i1")["procedure_id"], "ad_unlock_account")

    def test_no_proposal_when_not_locked_or_mid_down(self):
        for answer in (UNLOCKED, {"error": "MID Server did not answer"}):
            snow = FakeSnow(["KB-IAM-001"])
            with mock.patch("jarvis.mid.run", mid_returning(answer)[0]):
                handle(dict(TICKET), snow, FakeLLM(), "m")
            self.assertEqual(len(snow.notes), 1, answer)
            self.assertIsNone(snow.executions.pending("i1"))

    def test_disk_full_server_gets_cleanup_proposal_for_the_named_host(self):
        snow = FakeSnow(["RB-SRV-001"])
        run, calls = mid_returning({"mount": "/var/log/helios-portal", "use_percent": 84})
        with mock.patch("jarvis.mid.run", run):
            handle(dict(DISK), snow, FakeLLM(), "m")
        self.assertEqual(calls, [("ssh", {"host": "app01", "verb": "disk_usage"})])
        self.assertEqual(snow.executions.pending("i2")["params"], {"host": "app01"})

    def approve(self, snow, *answers, ticket=TICKET):
        run, calls = mid_returning(*answers)
        with mock.patch("jarvis.mid.run", run):
            handle_approve(dict(ticket), snow)
        return calls

    def proposed(self, approver="jane.agent", params=None):
        snow = FakeSnow(["KB-IAM-001"], approver=approver)
        snow.executions.propose(TICKET, "ad_unlock_account", "L1", params or {"account": "alex.rivera"})
        return snow

    def test_approved_unlock_runs_verifies_and_resolves(self):
        snow = self.proposed()
        calls = self.approve(snow, LOCKED, {"account": "alex.rivera", "unlocked": True}, UNLOCKED)
        self.assertEqual([c[0] for c in calls], ["lockout_status", "unlock_account", "lockout_status"])
        row = proposal_row(snow)
        self.assertEqual((row["status"], row["approved_by"]), ("succeeded", "jane.agent"))
        self.assertIn("Procedure done", snow.notes[-1])
        self.assertEqual(snow.fields[-1]["state"], "6")

    def test_no_approval_no_action(self):
        snow = self.proposed(approver=None)
        self.assertEqual(self.approve(snow), [])
        self.assertEqual(snow.notes, [])

    def test_not_run_when_no_longer_needed(self):
        snow = self.proposed()
        calls = self.approve(snow, UNLOCKED)
        self.assertEqual([c[0] for c in calls], ["lockout_status"])  # the unlock itself never ran
        self.assertEqual(proposal_row(snow)["status"], "not_needed")
        self.assertIn("no longer needed", snow.notes[-1])

    def test_failed_verification_leaves_the_ticket_open(self):
        snow = self.proposed()
        self.approve(snow, LOCKED, {"account": "alex.rivera", "unlocked": True}, LOCKED)
        self.assertEqual(proposal_row(snow)["status"], "failed")
        self.assertIsNone(snow.fields[-1])
        self.assertIn("NOT OK", snow.notes[-1])

    def test_tampered_parameters_are_refused(self):
        snow = self.proposed(params={"account": "x)(objectClass=*"})
        self.assertEqual(self.approve(snow), [])
        self.assertEqual(proposal_row(snow)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
