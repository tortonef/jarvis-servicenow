"""Poll ServiceNow for new incidents and post a Jarvis suggestion as a work note. Shared handlers for push mode."""
import datetime
import json
import os
import re
import time
from pathlib import Path

from jarvis import problems, procedures
from jarvis.agent import draft_article, suggest, triage
from jarvis.config import KB_TITLE, llm_from_env, snow_from_env
from jarvis.notify import notify_p1
from jarvis.snow import CHANGE_REQUESTED, OUTCOME, PROPOSAL

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


def caller_of(incident, snow):
    ref = incident.get("caller_id")
    return snow.get_user(ref["value"]) if isinstance(ref, dict) and ref.get("value") else None


def run_check(snow, incident, pid, params):
    """Run one L0 procedure and audit it. A MID outage becomes an error result, never an exception."""
    try:
        result = procedures.run(snow, procedures.load()[pid], params)
    except Exception as e:
        result = {"error": str(e)}
    if snow.executions:
        snow.executions.record_auto(incident, pid, params, result)
    return result


def diagnose_and_plan(incident, snow, doc_ids):
    """Diagnose, then suggest: run the L0 checks linked to the retrieved documents, and pick the first L1 whose
    propose_if rule holds on those results. Returns ({procedure: (params, result)}, (procedure, params) or None)."""
    catalog, caller = procedures.load(), caller_of(incident, snow)
    linked = procedures.for_docs(catalog, doc_ids)
    checks = {}
    for pid in (p for p in linked if catalog[p]["risk"] == "L0"):
        params = procedures.resolve(catalog[pid], incident, caller)
        if params is not None:
            checks[pid] = (params, run_check(snow, incident, pid, params))
    for pid in (p for p in linked if catalog[p]["risk"] in ("L1", "L2")):
        cond, params = catalog[pid]["propose_if"], procedures.resolve(catalog[pid], incident, caller)
        if params is not None and cond["check"] in checks and procedures.holds(cond, checks[cond["check"]][1]):
            return checks, (pid, params)
    return checks, None


def describe(pid, params):
    return f"{procedures.load()[pid]['title']} ({', '.join(f'{k} {v}' for k, v in params.items())})"


def handle(incident, snow, llm, model):
    text = f"{incident['short_description']} {incident.get('description', '')}"
    kb, similar = snow.search_kb(text), snow.similar_resolved(text)
    try:
        checks, proposal = diagnose_and_plan(incident, snow, [a["doc_id"] for a in kb if a.get("doc_id")])
    except Exception as e:  # diagnostics are a bonus: never lose the resolution note because of them
        print(f"{incident['number']}: diagnostics failed: {e}")
        checks, proposal = {}, None
    note = suggest(incident, kb, similar, llm, model,
                   {describe(pid, params): result for pid, (params, result) in checks.items()})
    if checks:
        note += "\n\nDiagnostics (read only, run on-prem through the MID Server):\n" + "\n".join(
            f"- {describe(pid, params)}: {procedures.summary(result)}" for pid, (params, result) in checks.items())
    try:
        options = snow.triage_options()
        fields, line = apply_triage(incident, triage(incident, options, llm, model), options)
    except Exception as e:  # triage is a bonus too
        print(f"{incident['number']}: triage failed: {e}")
        fields, line = {}, ""
    snow.add_work_note(incident["sys_id"], note + line, fields)
    snow.audit(incident["number"], "answer", [a["number"] for a in kb] + [i["number"] for i in similar],
               {"triage": fields, "checks": list(checks), "proposal": proposal and proposal[0]})
    if proposal and snow.executions:  # proposals need the execution log to be approved later
        propose(incident, snow, *proposal)
    try:
        problems.check_cluster(incident, snow, note)
    except Exception as e:  # problem detection is a bonus too
        print(f"{incident['number']}: problem check failed: {e}")
    if incident.get("priority") == "1":
        try:
            if notify_p1(incident, note, snow.instance):
                print(f"{incident['number']}: P1 sent to Slack")
        except Exception as e:  # the work note is already posted; a Slack outage must not hide it
            print(f"{incident['number']}: Slack notification failed: {e}")
    print(f"{incident['number']}: suggestion posted (KB: {[a['number'] for a in kb]}, checks: {list(checks)}, "
          f"proposal: {proposal and proposal[0]}){line.strip() and ' ' + line.strip()}")


def propose(incident, snow, pid, params):
    proc = procedures.load()[pid]
    execution_id = snow.executions.propose(incident, pid, proc["risk"], params)
    if proc["risk"] == "L2":
        return request_change(incident, snow, pid, params, execution_id)
    snow.add_work_note(incident["sys_id"], (
        f"{PROPOSAL} ({proc['risk']}, needs your approval): {describe(pid, params)}.\n"
        f"Why: the read-only check {proc['propose_if']['check']} matched the rule in the procedure catalog.\n"
        "Approve with the 'Approve Jarvis procedure' button: Jarvis runs it on-prem through the MID Server, "
        "checks the result and resolves the ticket if the check passes."))


def runbook_sections(snow, proc):
    """'## ' sections of the procedure's first runbook, from the knowledge base (empty without one)."""
    doc = snow.knowledge.document(proc["docs"][0]) if snow.knowledge else None
    sections = {}
    for part in re.split(r"(?m)^## ", doc["body"] if doc else ""):
        if part.strip():
            head, _, text = part.partition("\n")
            # Change plan fields are plain text: drop Markdown code and bold marks
            sections[head.strip().lower()] = text.replace("`", "").replace("**", "").strip()
    return doc, sections


def rule(cond):
    """'healthy equals True' for a propose_if / verify condition."""
    op = next(k for k in cond if k not in ("check", "field"))
    return f"{cond['field']} {op.replace('_', ' ')} {cond[op]}"


def request_change(incident, snow, pid, params, execution_id):
    """L2: no approve button. Jarvis files a Normal Change built from the runbook and sends it for approval; it runs
    the procedure only when the approved Change moves to Implement (handle_implement)."""
    proc = procedures.load()[pid]
    doc, sec = runbook_sections(snow, proc)
    start = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
    group = snow.first("sys_user_group", "name=Software")
    cond = proc["propose_if"]
    change = snow.create("change_request", {
        "type": "normal",
        "short_description": f"Jarvis: {describe(pid, params)}",
        "description": (f"Requested by Jarvis for incident {incident['number']}: the read-only check {cond['check']} matched "
                        f"the catalog rule ({rule(cond)}).\nRunbook: {doc['id'] + ' ' + doc['title'] if doc else proc['docs'][0]}.\n"
                        "Jarvis runs the procedure on-prem through the MID Server when this Change moves to Implement, "
                        "verifies it and closes the Change."),
        "justification": f"Incident {incident['number']}: {incident['short_description']}",
        "implementation_plan": "\n\n".join(f"{label}:\n{sec[key]}" for key, label in
                                           (("when to use", "When to use"), ("pre-checks", "Pre-checks"), ("steps", "Steps"))
                                           if sec.get(key)) or proc["title"],
        "backout_plan": sec.get("rollback") or "No rollback documented in the runbook: escalate to the owning team.",
        "test_plan": f"Jarvis re-runs {proc['verify']['check']} and expects {rule(proc['verify'])}.",
        "assignment_group": group["sys_id"] if group else "",
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": (start + datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "correlation_id": f"jarvis-exec-{execution_id}",
    })
    snow.update("change_request", change["sys_id"], {"state": "-4"})  # Assess: the Change model requests the approvals
    snow.executions.set_change(execution_id, change["number"])
    snow.add_work_note(incident["sys_id"], (
        f"{CHANGE_REQUESTED} {change['number']} for an L2 procedure: {describe(pid, params)}.\n"
        f"Why: the read-only check {cond['check']} matched the rule in the procedure catalog ({rule(cond)}).\n"
        "It affects other users, so it needs an approved Change. The Change carries the runbook steps, pre-checks and "
        "rollback; once approved and moved to Implement, Jarvis runs it, verifies it and closes the Change."))
    print(f"{incident['number']}: L2 {pid} -> {change['number']} sent for approval")


def handle_implement(change, snow, llm=None, model=None):
    """The approved Change moved to Implement: run its L2 procedure, verify, close the Change, resolve the incident.
    Trusts nothing in the request: re-reads the Change, needs it approved and in Implement, and the pending L2 in
    Jarvis's log must match its correlation id and number."""
    corr = change.get("correlation_id") or ""
    if not re.fullmatch(r"jarvis-exec-\d+", corr):
        return print(f"{change['number']}: not a Jarvis change")
    pending = snow.executions.get(int(corr.rsplit("-", 1)[1])) if snow.executions else None
    if not pending or pending["status"] != "proposed" or pending["risk"] != "L2" or pending["change_number"] != change["number"]:
        return print(f"{change['number']}: no matching pending L2 procedure, refusing to act")
    if change.get("approval") != "approved" or change.get("state") != "-1":
        return print(f"{change['number']}: not approved and in Implement, refusing to act")
    approvers = snow.approvers(change["sys_id"])
    approved_by = change["number"] + (f" ({', '.join(approvers)})" if approvers else "")
    incident = {"sys_id": pending["incident_sys_id"], "number": pending["ticket"]}
    if still_valid(snow, incident, pending, "L2", approved_by):
        ok, note = execute(snow, incident, pending, approved_by)
    else:
        ok, note = False, "[Jarvis] Procedure not run: it is no longer valid in the catalog."
    snow.update("change_request", change["sys_id"], {"work_notes": note, "state": "0"})  # Review
    snow.update("change_request", change["sys_id"], {"state": "3", "close_code": "successful" if ok else "unsuccessful",
                                                     "close_notes": note.replace("[Jarvis] ", "", 1)})
    print(f"{change['number']}: {pending['procedure_id']} {'ok' if ok else 'failed'}, change closed")


def handle_approve(incident, snow, llm=None, model=None):
    """Run the proposed L1 procedure once an agent approved it. Never trusts the caller of the endpoint: it needs the
    pending proposal in Jarvis's log, the agent's approval note in ServiceNow, a catalog entry, valid parameters, and
    the reason for the proposal must still be true."""
    pending = snow.executions.pending(incident["sys_id"]) if snow.executions else None
    if not pending:
        return print(f"{incident['number']}: no pending procedure, nothing to approve")
    approver = snow.approval_for_proposal(incident["sys_id"])
    if not approver:
        return print(f"{incident['number']}: no agent approval after the proposal, refusing to act")
    proc = procedures.load().get(pending["procedure_id"])
    if proc and proc["risk"] == "L2":  # L2 is approved on its Change, never with this button
        return print(f"{incident['number']}: the pending procedure is L2, it waits for its Change")
    if not still_valid(snow, incident, pending, "L1", approver):
        return
    execute(snow, incident, pending, approver)


def still_valid(snow, incident, pending, risk, approved_by):
    """The pending procedure still exists in the catalog at this risk level and its stored parameters still pass the
    catalog's validation (the database row could have been tampered with)."""
    proc, params = procedures.load().get(pending["procedure_id"]), pending["params"]
    if proc and proc["risk"] == risk and set(params) == set(proc["params"]) and \
            all(procedures.valid(proc["params"][k], v) for k, v in params.items()):
        return True
    snow.executions.finish(pending["id"], "failed", approved_by, {"error": "procedure or parameters no longer valid"})
    snow.add_work_note(incident["sys_id"], f"{OUTCOME} not run: it is no longer valid in the catalog.")
    return False


def execute(snow, incident, pending, approved_by):
    """Shared by L1 (approve button) and L2 (approved Change): re-check, run, verify, record, resolve the incident.
    Returns (ok, the outcome note)."""
    catalog = procedures.load()
    proc, params = catalog[pending["procedure_id"]], pending["params"]
    cond = proc["propose_if"]
    check_params = {k: params[k] for k in catalog[cond["check"]]["params"]}
    before = run_check(snow, incident, cond["check"], check_params)
    if not procedures.holds(cond, before):  # e.g. the account unlocked by itself meanwhile
        snow.executions.finish(pending["id"], "not_needed", approved_by, verify_result=before)
        note = f"{OUTCOME} not run, no longer needed: {describe(cond['check'], check_params)}: {procedures.summary(before)}."
        snow.add_work_note(incident["sys_id"], note)
        return False, note
    try:
        result = procedures.run(snow, proc, params)
    except Exception as e:
        result = {"error": str(e)}
    after = run_check(snow, incident, proc["verify"]["check"], check_params) if not result.get("error") else None
    ok = after is not None and procedures.holds(proc["verify"], after)
    snow.executions.finish(pending["id"], "succeeded" if ok else "failed", approved_by, result, after)
    note = (f"{OUTCOME} {'done' if ok else 'FAILED'}: {describe(pending['procedure_id'], params)}, approved by {approved_by}.\n"
            f"Result: {procedures.summary(result)}")
    if after is not None:
        note += f"\nVerification ({proc['verify']['check']}): {procedures.summary(after)} -> {'OK' if ok else 'NOT OK'}"
    fields = {"state": "6", "close_code": "Workaround provided",
              "close_notes": f"{proc['title']} ({', '.join(f'{k} {v}' for k, v in params.items())}) run by Jarvis on-prem "
                             f"after approval by {approved_by}. Verified: {procedures.summary(after)}."} if ok else None
    snow.add_work_note(incident["sys_id"], note + ("\nResolving the incident." if ok else "\nLeaving the incident open."), fields)
    snow.audit(incident["number"], "remediation", detail={"procedure": pending["procedure_id"], "params": params, "ok": ok})
    print(f"{incident['number']}: {pending['procedure_id']} approved by {approved_by}: {'ok' if ok else 'failed'}")
    return ok, note


def handle_feedback(incident, snow, llm=None, model=None):
    """A rating button was clicked: the vote and its author come from the agent's note in ServiceNow, not the request."""
    vote = snow.latest_feedback(incident["sys_id"])
    if not vote or not snow.db:
        return print(f"{incident['number']}: no feedback note to record")
    from jarvis.db import record_feedback
    record_feedback(snow.db, incident, *vote)
    print(f"{incident['number']}: feedback from {vote[0]}: {'helpful' if vote[1] else 'not helpful'}")


def handle_resolved(incident, snow, llm, model):
    """Turn a resolution nobody documented yet into a draft KB article, linked to the incident."""
    if not (incident.get("close_notes") or "").strip():
        return print(f"{incident['number']}: no resolution notes, nothing to document")
    if snow.draft_for(incident["sys_id"]):
        return print(f"{incident['number']}: KB article already drafted")
    text = f"{incident['short_description']} {incident.get('description', '')} {incident['close_notes']}"
    result = draft_article(incident, snow.kb_candidates(text), llm, model)
    if result is None:
        return print(f"{incident['number']}: unusable KB draft from the model, skipped")
    if "covered_by" in result:
        note = f"[Jarvis] KB check: this fix is already documented in {result['covered_by']}. No new article needed."
        snow.audit(incident["number"], "kb_covered", [result["covered_by"]])
    elif os.getenv("GITHUB_TOKEN") and os.getenv("DOCS_REPO"):  # docs as code: the gap becomes a pull request
        from jarvis import docs_pr
        path, text = docs_pr.article(incident, result)
        url = docs_pr.open_pr(os.environ["DOCS_REPO"], os.environ["GITHUB_TOKEN"], incident, result["title"], path, text,
                              os.getenv("DOCS_REF", "main"))
        if url is None:
            return print(f"{incident['number']}: knowledge article already proposed")
        snow.audit(incident["number"], "kb_draft", [url], {"title": result["title"]})
        note = (f"[Jarvis] Proposed knowledge article \"{result['title']}\" from this resolution: {url}\n"
                "It is a pull request: once reviewed and merged, it is published to the knowledge base.")
    else:
        art = snow.create("kb_knowledge", {"short_description": result["title"], "text": result["text"],
                                           "kb_knowledge_base": snow.kb_base(KB_TITLE)["sys_id"], "source": incident["sys_id"]})
        snow.audit(incident["number"], "kb_draft", [art["number"]], {"title": result["title"]})
        note = (f"[Jarvis] Drafted knowledge article {art['number']} \"{result['title']}\" from this resolution.\n"
                "It is a draft: review and publish it so the next agent finds the fix.")
    snow.add_work_note(incident["sys_id"], note)
    print(f"{incident['number']}: {note.splitlines()[0]}")


def lockout_note(r):
    """Work note text for a JarvisLdap.lockoutStatus result."""
    hhmm = lambda iso: iso[11:16] + " UTC"
    head = f"[Jarvis] Active Directory check (read only, helios.local via MID Server)\n\nAccount {r.get('account', '?')}: "
    if r.get("error"):
        return head + f"check failed: {r['error']}"
    if not r.get("found"):
        return head + "not found in the directory. Check the caller's user name."
    if r["locked"]:
        state = (f"LOCKED OUT since {hhmm(r['locked_since'])} after {r['bad_password_count']} bad passwords "
                 f"(threshold {r['lockout_threshold']})")
        state += f"; unlocks automatically at {hhmm(r['unlocks_at'])}." if r.get("unlocks_at") else "."
        state += "\nTo unlock now follow RB-AD-001; if it locks again, find the source with RB-AD-002."
    else:
        state = f"not locked out ({r['bad_password_count']} recent bad passwords)."
    return head + state + ("\nThe account is DISABLED." if r.get("disabled") else "")


def handle_diagnose(incident, snow, llm=None, model=None):
    """The 'Check AD account (Jarvis)' button: the ad_lockout_status procedure on demand. Changes nothing."""
    caller = caller_of(incident, snow)
    params = procedures.resolve(procedures.load()["ad_lockout_status"], incident, caller)
    if params is None:
        return snow.add_work_note(incident["sys_id"], "[Jarvis] Active Directory check skipped: the incident has no valid caller.")
    result = run_check(snow, incident, "ad_lockout_status", params)
    snow.add_work_note(incident["sys_id"], lockout_note(result))
    snow.audit(incident["number"], "diagnostic", detail={"check": "ad_lockout_status", "result": result})
    print(f"{incident['number']}: AD check {params['account']}: locked={result.get('locked')}")


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
