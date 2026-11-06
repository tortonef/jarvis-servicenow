"""Slack notification for P1 incidents, with Jarvis's suggestion attached."""
import os

import requests


def esc(text):
    # Slack mrkdwn control characters: also stops ticket text from triggering <!channel>-style mentions
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_message(incident, note, instance):
    lines = {k: v for k, v in (l.split(":", 1) for l in note.splitlines() if ":" in l)}
    pick = lambda key: esc(lines.get(key, "").strip()) or "n/a"
    url = f"{instance}/incident.do?sys_id={incident['sys_id']}"
    return {
        "text": f"P1 incident {incident['number']}: {esc(incident['short_description'])}",  # notification fallback
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"🚨 P1 incident {incident['number']}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*<{url}|{esc(incident['short_description'])}>*\n"
                                                                    f"{esc(incident.get('description', ''))[:500]}"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Jarvis: probable cause*\n{pick('Probable cause')}"},
                {"type": "mrkdwn", "text": f"*Confidence*\n{pick('Confidence')}\n*Sources*\n{pick('Sources')}"}]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "Full suggestion in the incident work notes. AI-generated, please verify."}]},
        ],
    }


def notify_p1(incident, note, instance):
    """Post to Slack if a webhook is configured. Returns True when Slack accepted the message."""
    webhook = os.getenv("NOTIFY_WEBHOOK_URL", "")
    if not webhook:
        return False
    r = requests.post(webhook, json=slack_message(incident, note, instance), timeout=10)
    r.raise_for_status()
    return True
