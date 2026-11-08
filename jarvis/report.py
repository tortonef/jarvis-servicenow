"""Weekly health report for the Service Desk and maintenance leads: what Jarvis did, what failed, what to fix in the
knowledge base. Posted to Slack (NOTIFY_WEBHOOK_URL) and printed.

Usage: python -m jarvis.report [--post]
"""
import datetime
import os
import sys

import requests

from jarvis.notify import esc


def build(conn, days=7, today=None):
    """Report text (Slack mrkdwn) from Jarvis's database."""
    today = today or datetime.date.today()
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    since = f"now() - interval '{int(days)} days'"
    answers = q(f"SELECT count(*), count(*) FILTER (WHERE NOT sources::text ~ '\"KB') FROM suggestion "
                f"WHERE kind = 'answer' AND created_at > {since}")[0]
    gaps = q(f"SELECT ticket FROM suggestion WHERE kind = 'answer' AND created_at > {since} AND NOT sources::text ~ '\"KB' "
             f"ORDER BY created_at DESC LIMIT 5")
    ss = q(f"SELECT count(*), count(*) FILTER (WHERE solved), count(*) FILTER (WHERE solved = false) FROM self_service "
           f"WHERE created_at > {since}")[0]
    runs = q(f"SELECT risk, status, count(*) FROM execution WHERE proposed_at > {since} GROUP BY 1, 2 ORDER BY 1, 2")
    failed = q(f"SELECT ticket, procedure_id FROM execution WHERE status = 'failed' AND proposed_at > {since} "
               f"ORDER BY id DESC LIMIT 5")
    problems = q(f"SELECT count(*) FROM suggestion WHERE kind = 'problem' AND created_at > {since}")[0][0]
    stale = q("SELECT id, title, review_by FROM document WHERE review_by < %s ORDER BY review_by LIMIT 10",
              today + datetime.timedelta(days=30))

    answered = (ss[1] or 0) + (ss[2] or 0)
    lines = [f"*Jarvis weekly report* ({(today - datetime.timedelta(days=days)).isoformat()} to {today.isoformat()})", "",
             f"*Service Desk*: {answers[0]} incidents answered; {answers[1]} without a matching KB article"
             + (f" (e.g. {', '.join(r[0] for r in gaps)})" if gaps else "") + ".",
             f"*Self-service*: {ss[0]} questions on the portal, {ss[1]} solved without a ticket, {ss[2]} turned into tickets"
             + (f" (deflection {100 * ss[1] // answered}%)" if answered else "") + ".",
             "*Procedures*: " + (", ".join(f"{risk} {status} {n}" for risk, status, n in runs) or "none") + "."]
    if failed:
        lines.append("*Failed procedures*: " + ", ".join(f"{t} {p}" for t, p in failed))
    lines.append(f"*Problems proposed*: {problems}.")
    lines.append("*Docs to review in the next 30 days*: " +
                 (", ".join(f"{i} {esc(t)} ({d.isoformat()})" for i, t, d in stale) if stale else "none") + ".")
    return "\n".join(lines)


def post(text):
    webhook = os.getenv("NOTIFY_WEBHOOK_URL", "")
    if not webhook:
        return False
    requests.post(webhook, json={"text": text}, timeout=10).raise_for_status()
    return True


def main():
    from jarvis.config import snow_from_env
    snow = snow_from_env("keyword")
    if not snow.db:
        raise SystemExit("the report needs DATABASE_URL")
    text = build(snow.db)
    print(text)
    if "--post" in sys.argv[1:]:
        print("posted to Slack" if post(text) else "NOTIFY_WEBHOOK_URL not set: not posted")


if __name__ == "__main__":
    main()
