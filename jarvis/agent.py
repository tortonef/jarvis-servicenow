"""Turn an incident + retrieved knowledge into a resolution suggestion for the operator."""
import html
import re

SYSTEM = """You are Jarvis, an assistant for IT Service Desk agents.
You receive a ticket, some Knowledge Base articles and similar resolved tickets.
Reply in English, in plain text (no markdown), with this structure:

Probable cause: <one sentence>
Suggested steps:
1. ...
2. ...
Sources: <KB and INC numbers used>
Confidence: high | medium | low

Use ONLY the information provided. If nothing is relevant, say so and suggest which team the ticket should be routed to."""

HEADER = "[Jarvis] Resolution suggestion (AI-generated, please verify)\n\n"


def strip_html(text, limit=1500):
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()[:limit]


def build_prompt(incident, kb, similar):
    parts = [f"TICKET {incident['number']}\nTitle: {incident['short_description']}\nDescription:{incident.get('description', '')}"]
    parts += [f"ARTICLE {a['number']}: {a['short_description']}\n{strip_html(a['text'])}" for a in kb]
    parts += [f"RESOLVED TICKET {i['number']}: {i['short_description']}\nResolution: {i['close_notes']}" for i in similar]
    if not kb and not similar:
        parts.append("No KB article or similar ticket found.")
    return "\n\n---\n\n".join(parts)


def suggest(incident, kb, similar, llm, model):
    resp = llm.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": build_prompt(incident, kb, similar)}],
    )
    # work notes are plain text: drop markdown the model adds despite the prompt
    return HEADER + resp.choices[0].message.content.replace("**", "").replace("`", "").strip()
