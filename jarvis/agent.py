"""Turn an incident + retrieved knowledge into a resolution suggestion for the operator."""
import html
import json
import re

TRIAGE = """Classify an IT incident for the Service Desk. Reply with JSON only:
{{"category": "<one category>", "assignment_group": "<one group>", "action": "unlock_account" or null}}
Categories: {cats}
Assignment groups: {groups}
Pick the group that would fix the issue; use "Service Desk" only for generic or unclear tickets.
Set "action" to "unlock_account" only if the user reports that their own account is locked out; otherwise null."""
SYSTEM = """You are Jarvis, an assistant for IT Service Desk agents.
You receive a ticket, some Knowledge Base articles and similar resolved tickets.
Reply in English, in plain text (no markdown), with this structure:

Probable cause: <one sentence>
Suggested steps:
1. ...
2. ...
Sources: <only the KB and INC numbers used, e.g. KB0010016, INC0010003>
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
    if out.get("action") == "unlock_account":
        result["action"] = "unlock_account"
    return result


KB_DRAFT = """You maintain the IT Knowledge Base. You receive a resolved incident, with the agent's resolution notes,
and the closest existing articles. Reply with JSON only.
If one of the articles already explains this fix: {"covered_by": "<article number>"}
Otherwise write a new article:
{"covered_by": null, "title": "<short, searchable title>", "symptom": "<what the user sees>",
 "cause": "<root cause, or empty if unknown>", "steps": ["<step>", "..."]}
Write in English. Use only facts from the incident; do not invent hostnames, tools or procedures."""


def draft_article(incident, candidates, llm, model):
    """Return {"covered_by": number}, {"title", "text"} for a new article, or None if the model output is unusable."""
    articles = "\n\n".join(f"ARTICLE {a['number']}: {a['short_description']}\n{strip_html(a['text'], 800)}" for a in candidates)
    resp = llm.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": KB_DRAFT},
                  {"role": "user", "content": f"INCIDENT {incident['number']}\nTitle: {incident['short_description']}\n"
                                              f"Description: {incident.get('description', '')}\n"
                                              f"Resolution notes: {incident.get('close_notes', '')}\n\n{articles or 'No related articles.'}"}],
    )
    try:
        out = json.loads(resp.choices[0].message.content)
    except (ValueError, TypeError):
        return None
    if not isinstance(out, dict):
        return None
    if out.get("covered_by"):
        # only trust a number we actually showed the model
        number = str(out["covered_by"])
        return {"covered_by": number} if number in {a["number"] for a in candidates} else None
    title, steps = out.get("title"), out.get("steps")
    if not isinstance(title, str) or not title.strip() or not isinstance(steps, list) or not steps \
            or not all(isinstance(s, str) and s.strip() for s in steps):
        return None
    e = html.escape  # model output goes into article HTML
    cause = str(out.get("cause") or "").strip()
    text = (f"<h3>Symptom</h3><p>{e(str(out.get('symptom', '')))}</p>"
            + (f"<h3>Cause</h3><p>{e(cause)}</p>" if cause else "")
            + "<h3>Resolution</h3><ol>" + "".join(f"<li>{e(s)}</li>" for s in steps) + "</ol>"
            + f"<p><em>Drafted by Jarvis from {e(incident['number'])}. Review before publishing.</em></p>")
    return {"title": title.strip()[:160], "text": text}
