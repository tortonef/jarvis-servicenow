"""Knowledge gaps as pull requests: a fix nobody documented becomes a Markdown article on a branch of the docs repo.
CI validates it, a human reviews and merges it, and the docs sync publishes it to ServiceNow like any other doc."""
import base64
import datetime
import re

import yaml

API = "https://api.github.com"


def one_line(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def article(incident, draft, today=None):
    """(path, Markdown text) for a draft from agent.draft_article. The id carries the incident number, so two open
    pull requests can never pick the same id; the reviewer may rename it to a proper area before merging."""
    today = today or datetime.date.today()
    number = incident["number"]
    slug = re.sub(r"[^a-z0-9]+", "-", draft["title"].lower()).strip("-")[:60] or "article"
    meta = {"id": f"KB-{re.sub(r'[^A-Z0-9]', '', number.upper())}-001", "title": draft["title"],
            "audience": ["service-desk"], "systems": [one_line(incident.get("category")) or "general"],
            "symptoms": [one_line(incident["short_description"])[:120]], "owner": "service-desk",
            "review_by": today + datetime.timedelta(days=180)}
    # model output is flattened to one line per item, so it can't add sections or break the front matter
    body = [f"## Symptom\n{one_line(draft['symptom']) or one_line(incident['short_description'])}"]
    if one_line(draft.get("cause")):
        body.append(f"## Cause\n{one_line(draft['cause'])}")
    body.append("## Resolution\n" + "\n".join(f"{i}. {one_line(s)}" for i, s in enumerate(draft["steps"], 1)))
    body.append(f"*Drafted by Jarvis from {number}. Check every step before merging.*")
    text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + "\n\n".join(body) + "\n"
    return f"knowledge/articles/{slug}-{number.lower()}.md", text


def open_pr(repo, token, incident, title, path, text, base="main"):
    """Branch jarvis/kb-<incident>, one commit with the article, a pull request. Returns its URL, or None when the
    branch already exists (the gap was already proposed)."""
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})

    def call(method, url, **kw):
        r = s.request(method, f"{API}/repos/{repo}{url}", timeout=30, **kw)
        if r.status_code == 422 and url == "/git/refs":
            return None
        r.raise_for_status()
        return r.json()

    branch = f"jarvis/kb-{incident['number'].lower()}"
    sha = call("GET", f"/git/ref/heads/{base}")["object"]["sha"]
    if call("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha}) is None:
        return None
    call("PUT", f"/contents/{path}", json={"message": f"KB draft from {incident['number']}", "branch": branch,
                                           "content": base64.b64encode(text.encode()).decode()})
    pr = call("POST", "/pulls", json={
        "title": f"KB: {one_line(title)}", "head": branch, "base": base,
        "body": f"Jarvis found no article for the fix in {incident['number']} and drafted one from the resolution "
                "notes.\n\nBefore merging: check every step, set a proper `id` area (e.g. KB-NET-004), `systems` "
                "and `audience` (add `end-user` only if employees can follow it alone). Merging publishes it to "
                "the ServiceNow knowledge base on the next sync."})
    return pr["html_url"]
