"""Poll ServiceNow for new incidents and post a Jarvis suggestion as a work note. Shared handlers for push mode."""
import json
import os
import time
from pathlib import Path

from jarvis import procedures
from jarvis.agent import draft_article, suggest, triage
from jarvis.config import KB_TITLE, llm_from_env, snow_from_env
from jarvis.notify import notify_p1
from jarvis.snow import PROPOSAL

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
    for pid in (p for p in linked if catalog[p]["risk"] == "L1"):
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
    snow.executions.propose(incident, pid, proc["risk"], params)
    snow.add_work_note(incident["sys_id"], (
        f"{PROPOSAL} ({proc['risk']}, needs your approval): {describe(pid, params)}.\n"
        f"Why: the read-only check {proc['propose_if']['check']} matched the rule in the procedure catalog.\n"
        "Approve with the 'Approve Jarvis procedure' button: Jarvis runs it on-prem through the MID Server, "
        "checks the result and resolves the ticket if the check passes."))


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
    catalog = procedures.load()
    proc, params = catalog.get(pending["procedure_id"]), pending["params"]
    if not proc or proc["risk"] != "L1" or set(params) != set(proc["params"]) or \
            not all(procedures.valid(proc["params"][k], v) for k, v in params.items()):
        snow.executions.finish(pending["id"], "failed", approver, {"error": "procedure or parameters no longer valid"})
        return snow.add_work_note(incident["sys_id"], "[Jarvis] Procedure not run: it is no longer valid in the catalog.")
    cond = proc["propose_if"]
    check_params = {k: params[k] for k in catalog[cond["check"]]["params"]}
    before = run_check(snow, incident, cond["check"], check_params)
    if not procedures.holds(cond, before):  # e.g. the account unlocked by itself meanwhile
        snow.executions.finish(pending["id"], "not_needed", approver, verify_result=before)
        return snow.add_work_note(incident["sys_id"], f"[Jarvis] Procedure not run, no longer needed: "
                                                      f"{describe(cond['check'], check_params)}: {procedures.summary(before)}.")
    try:
        result = procedures.run(snow, proc, params)
    except Exception as e:
        result = {"error": str(e)}
    after = run_check(snow, incident, proc["verify"]["check"], check_params) if not result.get("error") else None
    ok = after is not None and procedures.holds(proc["verify"], after)
    snow.executions.finish(pending["id"], "succeeded" if ok else "failed", approver, result, after)
    note = (f"[Jarvis] Procedure {'done' if ok else 'FAILED'}: {describe(pending['procedure_id'], params)}, approved by {approver}.\n"
            f"Result: {procedures.summary(result)}")
    if after is not None:
        note += f"\nVerification ({proc['verify']['check']}): {procedures.summary(after)} -> {'OK' if ok else 'NOT OK'}"
    fields = {"state": "6", "close_code": "Workaround provided",
              "close_notes": f"{proc['title']} ({', '.join(f'{k} {v}' for k, v in params.items())}) run by Jarvis on-prem "
                             f"after approval by {approver}. Verified: {procedures.summary(after)}."} if ok else None
    snow.add_work_note(incident["sys_id"], note + ("\nResolving the incident." if ok else "\nLeaving the incident open."), fields)
    snow.audit(incident["number"], "remediation", detail={"procedure": pending["procedure_id"], "params": params, "ok": ok})
    print(f"{incident['number']}: {pending['procedure_id']} approved by {approver}: {'ok' if ok else 'failed'}")


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
