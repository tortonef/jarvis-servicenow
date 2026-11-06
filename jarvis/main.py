"""Poll ServiceNow for new incidents and post a Jarvis suggestion as a work note."""
import json
import os
import time
from pathlib import Path

from jarvis.agent import suggest, triage
from jarvis.config import llm_from_env, snow_from_env

# shortcut: processed ids in a local file; move to a custom field on incident if several Jarvis instances run
STATE = Path("state.json")


def apply_triage(incident, suggested, options):
    """Fill only fields nobody has set yet; report every suggestion in the note."""
    cats, groups = options
    fields, parts = {}, []
    if "category" in suggested:
        empty = incident.get("category") in ("", None, "inquiry")  # "inquiry" is the incident form default
        if empty:
            fields["category"] = suggested["category"]
        parts.append(f"category {cats[suggested['category']]} ({'set' if empty else 'suggested, already filled'})")
    if "assignment_group" in suggested:
        empty = not incident.get("assignment_group")
        if empty:
            fields["assignment_group"] = groups[suggested["assignment_group"]]
        parts.append(f"assignment group {suggested['assignment_group']} ({'set' if empty else 'suggested, already filled'})")
    return fields, ("\n\nTriage: " + ", ".join(parts)) if parts else ""


def handle(incident, snow, llm, model):
    text = f"{incident['short_description']} {incident.get('description', '')}"
    kb, similar = snow.search_kb(text), snow.similar_resolved(text)
    note = suggest(incident, kb, similar, llm, model)
    try:
        options = snow.triage_options()
        fields, line = apply_triage(incident, triage(incident, options, llm, model), options)
    except Exception as e:  # triage is a bonus: never lose the resolution note because of it
        print(f"{incident['number']}: triage failed: {e}")
        fields, line = {}, ""
    snow.add_work_note(incident["sys_id"], note + line, fields)
    print(f"{incident['number']}: suggestion posted (KB: {[a['number'] for a in kb]}, INC: {[i['number'] for i in similar]}){line.strip() and ' ' + line.strip()}")


def main():
    snow = snow_from_env()
    llm, model = llm_from_env()
    done = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    print(f"Jarvis watching {os.environ['SNOW_INSTANCE']} ...")
    while True:
        for inc in snow.new_incidents():
            if inc["sys_id"] in done:
                continue
            try:
                handle(inc, snow, llm, model)
            except Exception as e:  # one bad ticket or LLM rate limit must not stop the loop; retried next poll
                print(f"{inc['number']}: failed: {e}")
                continue
            done.add(inc["sys_id"])
            STATE.write_text(json.dumps(sorted(done)))
        time.sleep(int(os.getenv("POLL_SECONDS", "30")))


if __name__ == "__main__":
    main()
