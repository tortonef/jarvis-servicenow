"""Watcher: on every background loop, count the open backlog, find incidents close to or past their SLA and put a
resolution suggestion on them. It changes no incident field: work notes and Slack alerts only.

Usage: python -m jarvis.watcher   (one pass, the same the server runs every DOCS_POLL_SECONDS)
"""
import datetime
import os
import re

from jarvis.notify import notify_p1
from jarvis.snow import SUGGESTION

OPEN = "active=true^stateNOT IN6,7,8"  # Resolved incidents keep active=true until closed


def level(sla, now, warn):
    """'breached', 'warning' or None for one task_sla row."""
    if sla.get("stage") == "paused":  # the clock is stopped: planned_end moves on resume
        return None
    try:
        pct = float(sla.get("percentage") or 0)
    except ValueError:
        pct = 0.0
    end = sla.get("planned_end_time") or ""
    # shortcut: percentage is refreshed by ServiceNow's SLA jobs and can lag; a past planned end counts as breached
    if sla.get("has_breached") == "true" or pct >= 100 or (end and end < now.strftime("%Y-%m-%d %H:%M:%S")):
        return "breached"
    return "warning" if pct >= warn else None


def snapshot(snow, worst):
    """One backlog_snapshot row per priority x state x group of open incidents, with at-risk and breached counts.
    worst: incident sys_id -> (level, sla row)."""
    rows = snow.stats("incident", OPEN, "priority,state,assignment_group")
    ids = ",".join({g["assignment_group"] for g, _ in rows if g.get("assignment_group")})
    names = {g["sys_id"]: g["name"] for g in snow.query("sys_user_group", f"sys_idIN{ids}", ["sys_id", "name"], 200)} if ids else {}
    risk = {}
    for lvl, sla in worst.values():
        key = (sla.get("task.priority", ""), sla.get("task.state", ""), sla.get("task.assignment_group", ""))
        risk.setdefault(key, {"warning": 0, "breached": 0})[lvl] += 1
    out = []
    for g, n in rows:
        key = (g.get("priority", ""), g.get("state", ""), g.get("assignment_group", ""))
        r = risk.get(key, {"warning": 0, "breached": 0})
        out.append((key[0], key[1], names.get(key[2], ""), n, r["warning"], r["breached"]))
    with snow.db.cursor() as cur:
        cur.executemany("INSERT INTO backlog_snapshot (priority, state, assignment_group, open, at_risk, breached) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", out)
    return out


def cause_and_steps(note):
    """'Probable cause' up to 'Sources' from a Jarvis suggestion note."""
    m = re.search(r"(Probable cause:.*?)(?:\nSources:|\Z)", note or "", re.S)
    return m.group(1).strip() if m else ""


def alert(snow, llm, model, sla, lvl):
    """Warn once per SLA and level: suggestion on the ticket (a new one if Jarvis has none yet), then Slack."""
    if snow.db.execute("SELECT 1 FROM sla_alert WHERE task_sla_sys_id = %s AND level = %s", (sla["sys_id"], lvl)).fetchone():
        return False
    incident = snow.get_incident(sla["task.sys_id"])
    if not incident:
        return False
    prev = snow.latest_note(incident["sys_id"], SUGGESTION)
    if prev is None:
        from jarvis.main import handle
        handle(incident, snow, llm, model)  # full suggestion: KB, history, diagnostics, triage
        prev = snow.latest_note(incident["sys_id"], SUGGESTION)
    pct, end = float(sla.get("percentage") or 0), (sla.get("planned_end_time") or "")[:16]
    head = f"[Jarvis] SLA {lvl}: {sla['sla.name']} at {pct:.0f}%" + (f", due {end} UTC" if end else "") + "."
    steps = cause_and_steps(prev and prev["value"])
    snow.add_work_note(incident["sys_id"], head + (f"\n\nFrom Jarvis's resolution suggestion:\n{steps}" if steps else
                                                   "\n\nNo resolution suggestion available: route the ticket or escalate."))
    try:
        notify_p1(incident, steps, snow.instance, f"⏰ SLA {lvl}: {incident['number']}")
    except Exception as e:  # the work note is posted; Slack is a bonus
        print(f"{incident['number']}: Slack SLA alert failed: {e}")
    snow.db.execute("INSERT INTO sla_alert (task_sla_sys_id, level, ticket, incident_sys_id, sla_name, percentage, planned_end, "
                    "priority, assignment_group) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (sla["sys_id"], lvl, incident["number"], incident["sys_id"], sla["sla.name"], pct,
                     sla.get("planned_end_time"), sla.get("task.priority"), sla.get("task.assignment_group.name")))
    snow.audit(incident["number"], "sla_alert", [], {"sla": sla["sla.name"], "level": lvl, "percentage": pct})
    print(f"{incident['number']}: SLA {lvl} ({sla['sla.name']} {pct:.0f}%)")
    return True


def watch(snow, llm, model, now=None):
    """One pass. Needs the database: it is what keeps an alert from being sent twice."""
    if not snow.db:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    warn = float(os.getenv("SLA_WARN_PERCENT", "75"))
    worst = {}  # incident -> its worst SLA: an incident counts once even with response and resolution SLAs
    alerts = []
    for sla in snow.active_slas():
        lvl = level(sla, now, warn)
        if lvl:
            alerts.append((sla, lvl))
            inc = sla.get("task.sys_id")
            if inc not in worst or (lvl == "breached" and worst[inc][0] == "warning"):
                worst[inc] = (lvl, sla)
    snapshot(snow, worst)
    sent = 0
    for sla, lvl in alerts:
        try:
            sent += alert(snow, llm, model, sla, lvl)
        except Exception as e:  # one ticket or an LLM rate limit must not stop the pass; retried next loop
            print(f"{sla.get('task.number')}: SLA alert failed: {e}")
    return sent


def main():
    from jarvis.config import llm_from_env, snow_from_env
    snow = snow_from_env()
    if not snow.db:
        raise SystemExit("the watcher needs DATABASE_URL")
    llm, model = llm_from_env()
    print(f"watcher: {watch(snow, llm, model)} SLA alerts sent")


if __name__ == "__main__":
    main()
