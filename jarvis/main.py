"""Poll ServiceNow for new incidents and post a Jarvis suggestion as a work note."""
import json
import os
import time
from pathlib import Path

from jarvis.agent import suggest
from jarvis.config import llm_from_env, snow_from_env

# shortcut: processed ids in a local file; move to a custom field on incident if several Jarvis instances run
STATE = Path("state.json")


def handle(incident, snow, llm, model):
    text = f"{incident['short_description']} {incident.get('description', '')}"
    kb, similar = snow.search_kb(text), snow.similar_resolved(text)
    note = suggest(incident, kb, similar, llm, model)
    snow.add_work_note(incident["sys_id"], note)
    print(f"{incident['number']}: suggestion posted (KB: {[a['number'] for a in kb]}, INC: {[i['number'] for i in similar]})")


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
