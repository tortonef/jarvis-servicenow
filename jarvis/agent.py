"""Turn an incident + retrieved knowledge into a resolution suggestion for the operator."""
import html
import json
import re

TRIAGE = """Classify an IT incident for the Service Desk. Reply with JSON only:
{{"category": "<one category>", "assignment_group": "<one group>"}}
Categories: {cats}
Assignment groups: {groups}
Pick the group that would fix the issue; use "Service Desk" only for generic or unclear tickets."""
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


def triage(incident, options, llm, model):
    """Suggest category and assignment group. LLM output is untrusted: keep only values that exist in ServiceNow."""
    cats, groups = options
    resp = llm.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": TRIAGE.format(cats=", ".join(cats.values()), groups=", ".join(groups))},
                  {"role": "user", "content": f"Title: {incident['short_description']}\nDescription: {incident.get('description', '')}"}],
    )
    try:
        out = json.loads(resp.choices[0].message.content)
    except (ValueError, TypeError):
        return {}
    if not isinstance(out, dict):
        return {}
    by_name = {k.lower(): v for v, label in cats.items() for k in (v, label)}
    cat, group = str(out.get("category", "")).lower(), str(out.get("assignment_group", ""))
    result = {}
    if cat in by_name:
        result["category"] = by_name[cat]
    if group in groups:
        result["assignment_group"] = group
    return result
