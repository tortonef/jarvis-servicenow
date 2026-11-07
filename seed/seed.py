"""Load demo incidents and the lockout demo user into a ServiceNow PDI. Safe to re-run: skips records that already exist.
KB articles are not seeded: they come from knowledge/ through the Jarvis KB sync."""
import json
from pathlib import Path

from jarvis.config import snow_from_env

HERE = Path(__file__).parent


def main():
    snow = snow_from_env("keyword")  # no search here: skip loading the embedding model
    # Demo caller whose user name matches the lab AD account (lock it there: lab/lock-user.sh alex.rivera)
    user = {"user_name": "alex.rivera", "first_name": "Alex", "last_name": "Rivera", "email": "alex.rivera@example.com"}
    rec = snow.first("sys_user", "user_name=alex.rivera")
    if rec and rec.get("locked_out") == "true":  # the ServiceNow flag was only a stand-in before the lab AD existed
        snow.update("sys_user", rec["sys_id"], {"locked_out": "false"})
    rec = rec or snow.create("sys_user", user)
    print("User", rec["user_name"], "ready")

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
