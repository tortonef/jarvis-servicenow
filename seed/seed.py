"""Load demo KB articles and incidents into a ServiceNow PDI. Safe to re-run: skips records that already exist."""
import json
from pathlib import Path

from jarvis.config import KB_TITLE, snow_from_env

HERE = Path(__file__).parent


def main():
    snow = snow_from_env()
    # Own KB with "Instant Publish": the stock "IT" KB uses an approval flow that keeps API-created articles in draft
    flow = snow.first("sys_hub_flow", "name=Knowledge - Instant Publish")
    kb_base = snow.first("kb_knowledge_base", f"title={KB_TITLE}") or snow.create(
        "kb_knowledge_base", {"title": KB_TITLE, "kb_publish_flow": flow["sys_id"] if flow else ""})

    drafts = 0
    for art in json.loads((HERE / "kb_articles.json").read_text(encoding="utf-8")):
        rec = snow.first("kb_knowledge", f"short_description={art['short_description']}")
        if not rec:
            rec = snow.create("kb_knowledge", {**art, "kb_knowledge_base": kb_base["sys_id"]})
            print("KB", rec["number"], art["short_description"])
        drafts += rec["workflow_state"] != "published"
    if drafts:
        # ServiceNow ignores workflow_state changes via the Table API; publishing must run server-side
        print(f"\n{drafts} KB articles are drafts. Paste seed/publish_kb.js into System Definition > Scripts - Background and run it.\n")

    incidents = json.loads((HERE / "incidents.json").read_text(encoding="utf-8"))
    for inc in incidents["resolved"]:
        if snow.first("incident", f"short_description={inc['short_description']}"):
            continue
        rec = snow.create("incident", {**inc, "state": "6", "close_code": "Workaround provided"})
        print("Resolved", rec["number"], inc["short_description"])
    for inc in incidents["open"]:
        if snow.first("incident", f"short_description={inc['short_description']}"):
            continue
        rec = snow.create("incident", {**inc})
        print("Open", rec["number"], inc["short_description"])


if __name__ == "__main__":
    main()
