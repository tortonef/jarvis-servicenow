"""Problem management: when several open incidents describe the same thing, propose a Problem and link them."""
import re

WINDOW_HOURS = 24
MIN_INCIDENTS = 3   # this incident plus at least 2 others
# Same symptom from different people scores 0.83-0.89 with bge-small; but "VPN 809 from a hotel" scores 0.82 against an
# office-wide VPN outage, so similarity alone can't tell a shared cause: the Problem is a proposal (state New) and the
# problem manager unlinks incidents with a different cause.
SIMILARITY = 0.8
FIELDS = ["short_description", "description"]
# Incidents point at their Problem through task.parent: this PDI has no incident.problem_id (it comes with the Problem
# Management plugin), and a Problem is a task, so the standard parent reference works on any instance.
LINK = "parent"


def check_cluster(incident, snow, note=""):
    """Link this incident to an open Problem a similar incident already points to, or create one when enough open
    incidents match. Returns the Problem number, or None."""
    if not snow.semantic:
        return None
    # still-open incidents only: a Resolved incident keeps active=true until it is closed
    recent = snow.query("incident", f"active=true^stateNOT IN6,7,8^sys_created_on>=javascript:gs.hoursAgoStart({WINDOW_HOURS})"
                                    f"^sys_id!={incident['sys_id']}",
                        ["sys_id", "number", "short_description", "description", LINK, "sys_updated_on"], 200)
    text = f"{incident['short_description']} {incident.get('description', '')}"
    similar = snow.semantic.top(text, recent, FIELDS, k=50, min_score=SIMILARITY)
    for r in similar:  # an open Problem already covers this: join it
        ref = r.get(LINK)
        problem = snow.get("problem", ref["value"]) if isinstance(ref, dict) and ref.get("value") else None
        if problem and problem.get("active") == "true":
            snow.add_work_note(incident["sys_id"], f"[Jarvis] Linked to {problem['number']}: same symptoms as {r['number']}.",
                               {LINK: problem["sys_id"]})
            return problem["number"]
    if len(similar) + 1 < MIN_INCIDENTS:
        return None
    cause = re.search(r"Probable cause: (.+)", note)
    members = [incident] + similar
    listing = "\n".join(f"- {m['number']}: {m['short_description']}" for m in members)
    problem = snow.create("problem", {
        "short_description": f"Jarvis: {len(members)} similar incidents - {incident['short_description']}"[:160],
        "description": (f"Proposed by Jarvis: {len(members)} open incidents in the last {WINDOW_HOURS} hours describe the "
                        f"same symptoms.\n\n{listing}"
                        + (f"\n\nLikely cause (from Jarvis's analysis of {incident['number']}): {cause.group(1)}" if cause else "")
                        + "\n\nSimilarity is about symptoms, not causes: unlink any incident with a different cause."),
        "first_reported_by_task": incident["sys_id"],
    })
    for m in members:
        snow.add_work_note(m["sys_id"], f"[Jarvis] Linked to {problem['number']}: {len(members)} open incidents with the "
                                        "same symptoms.", {LINK: problem["sys_id"]})
    snow.audit(incident["number"], "problem", [m["number"] for m in members], {"problem": problem["number"]})
    print(f"{incident['number']}: proposed {problem['number']} for {[m['number'] for m in members]}")
    return problem["number"]
