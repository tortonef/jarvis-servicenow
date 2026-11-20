"""Watcher: SLA levels, dedup of alerts, reuse of an existing suggestion vs a new one. ServiceNow and the database are faked."""
import datetime
import unittest
from unittest import mock

from jarvis import watcher

NOW = datetime.datetime(2026, 11, 20, 12, 0, tzinfo=datetime.timezone.utc)
NOTE = ("[Jarvis] Resolution suggestion (AI-generated, please verify)\n\nProbable cause: VPN ports blocked\n"
        "Suggested steps:\n1. Open port 500\nSources: KB0010016\nConfidence: high")


def sla(sys_id, inc, pct, breached="false", end="2026-11-20 14:00:00", stage="in_progress"):
    return {"sys_id": sys_id, "sla.name": "P2 resolution", "percentage": str(pct), "has_breached": breached,
            "planned_end_time": end, "stage": stage, "task.sys_id": inc, "task.number": f"INC-{inc}", "task.priority": "2",
            "task.state": "2", "task.assignment_group": "g1", "task.assignment_group.name": "Network"}


class FakeDb:
    def __init__(self):
        self.alerts, self.snapshots = set(), []

    def execute(self, query, args=()):
        if query.startswith("SELECT 1 FROM sla_alert"):
            return mock.Mock(fetchone=lambda: (1,) if tuple(args) in self.alerts else None)
        if query.startswith("INSERT INTO sla_alert"):
            self.alerts.add((args[0], args[1]))
        return mock.Mock()

    def cursor(self):
        db = self
        class Cur:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def executemany(self, q, rows): db.snapshots.append(list(rows))
        return Cur()


class FakeSnow:
    instance = "https://dev1.service-now.com"

    def __init__(self, slas, notes=None):
        self.db, self.slas, self.notes, self.posted, self.audits = FakeDb(), slas, dict(notes or {}), [], []

    def active_slas(self):
        return self.slas

    def stats(self, table, query, group_by, display=False):
        return [({"priority": "2", "state": "2", "assignment_group": "g1"}, 4), ({"priority": "3", "state": "1", "assignment_group": ""}, 2)]

    def query(self, table, query, fields=None, limit=20):
        return [{"sys_id": "g1", "name": "Network"}]

    def get_incident(self, sys_id):
        return {"sys_id": sys_id, "number": f"INC-{sys_id}", "short_description": "VPN down", "priority": "2"}

    def latest_note(self, sys_id, prefix):
        return {"value": self.notes[sys_id]} if sys_id in self.notes else None

    def add_work_note(self, sys_id, note, fields=None):
        self.posted.append((sys_id, note, fields))

    def audit(self, ticket, kind, sources=(), detail=None):
        self.audits.append((ticket, kind))


class TestWatcher(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(watcher.level(sla("s", "i", 50), NOW, 75), None)
        self.assertEqual(watcher.level(sla("s", "i", 80), NOW, 75), "warning")
        self.assertEqual(watcher.level(sla("s", "i", 80, breached="true"), NOW, 75), "breached")
        self.assertEqual(watcher.level(sla("s", "i", 60, end="2026-11-20 11:00:00"), NOW, 75), "breached")  # lagging percentage
        self.assertEqual(watcher.level(sla("s", "i", 120, stage="paused"), NOW, 75), None)
        self.assertEqual(watcher.level(sla("s", "i", "", end=""), NOW, 75), None)

    def test_alert_reuses_suggestion_once_and_counts_backlog(self):
        snow = FakeSnow([sla("s1", "a", 82), sla("s2", "b", 30)], {"a": NOTE})
        with mock.patch("jarvis.watcher.notify_p1") as slack:
            self.assertEqual(watcher.watch(snow, None, "m", NOW), 1)
            self.assertEqual(watcher.watch(snow, None, "m", NOW), 0)  # second pass: no duplicate
        (sys_id, note, fields), = snow.posted
        self.assertEqual((sys_id, fields), ("a", None))           # work note only, no field changed
        self.assertIn("SLA warning: P2 resolution at 82%, due 2026-11-20 14:00 UTC", note)
        self.assertIn("Probable cause: VPN ports blocked", note)
        self.assertIn("1. Open port 500", note)
        self.assertNotIn("Sources", note)
        self.assertIn("SLA warning", slack.call_args[0][3])
        self.assertEqual(snow.audits, [("INC-a", "sla_alert")])
        self.assertEqual(snow.db.snapshots[0], [("2", "2", "Network", 4, 1, 0), ("3", "1", "", 2, 0, 0)])

    def test_breach_after_warning_alerts_again(self):
        snow = FakeSnow([sla("s1", "a", 82)], {"a": NOTE})
        with mock.patch("jarvis.watcher.notify_p1"):
            watcher.watch(snow, None, "m", NOW)
            snow.slas = [sla("s1", "a", 101, breached="true")]
            self.assertEqual(watcher.watch(snow, None, "m", NOW), 1)
        self.assertIn("SLA breached", snow.posted[-1][1])
        self.assertEqual(snow.db.snapshots[-1][0][4:], (0, 1))

    def test_no_suggestion_yet_runs_the_full_handler(self):
        snow = FakeSnow([sla("s1", "a", 90)])
        def handle(incident, s, llm, model):
            s.notes[incident["sys_id"]] = NOTE
        with mock.patch("jarvis.main.handle", side_effect=handle) as h, mock.patch("jarvis.watcher.notify_p1"):
            watcher.watch(snow, "llm", "m", NOW)
        h.assert_called_once()
        self.assertIn("Probable cause: VPN ports blocked", snow.posted[-1][1])

    def test_one_failing_ticket_does_not_stop_the_pass(self):
        snow = FakeSnow([sla("s1", "a", 90), sla("s2", "b", 90)], {"a": NOTE, "b": NOTE})
        real = snow.get_incident
        snow.get_incident = lambda sys_id: (_ for _ in ()).throw(RuntimeError("503")) if sys_id == "a" else real(sys_id)
        with mock.patch("jarvis.watcher.notify_p1"):
            self.assertEqual(watcher.watch(snow, None, "m", NOW), 1)
        self.assertEqual(snow.posted[0][0], "b")

    def test_old_breaches_are_counted_not_alerted_and_alerts_are_capped(self):
        old = sla("old", "z", 5000, breached="true", end="2018-10-17 06:00:00")
        snow = FakeSnow([old] + [sla(f"s{i}", f"i{i}", 90) for i in range(watcher.MAX_ALERTS + 3)],
                        {f"i{i}": NOTE for i in range(watcher.MAX_ALERTS + 3)})
        with mock.patch("jarvis.watcher.notify_p1"):
            self.assertEqual(watcher.watch(snow, None, "m", NOW), watcher.MAX_ALERTS)
            self.assertEqual(watcher.watch(snow, None, "m", NOW), 3)  # the rest on the next pass
        self.assertNotIn("z", [p[0] for p in snow.posted])
        self.assertEqual(sum(r[5] for r in snow.db.snapshots[0]), 1)  # still counted as breached

    def test_without_database_does_nothing(self):
        snow = FakeSnow([sla("s1", "a", 90)])
        snow.db = None
        self.assertIsNone(watcher.watch(snow, None, "m", NOW))


if __name__ == "__main__":
    unittest.main()
