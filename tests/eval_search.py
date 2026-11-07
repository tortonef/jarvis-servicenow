"""Retrieval quality on the Helios knowledge base: keyword vs semantic vs hybrid (PostgreSQL), with tickets phrased
the way users and engineers write them. The hybrid run is the CI quality gate.

Usage: python -m tests.eval_search            (hybrid needs TEST_DATABASE_URL; exits 1 below MIN_HYBRID)
"""
import os
import sys
from pathlib import Path

from jarvis.knowledge import load_dir
from jarvis.snow import keywords, rank

DOCS = load_dir(Path(__file__).parent.parent / "knowledge")
RECORDS = [{"sys_id": d["id"], "number": d["id"], "short_description": d["title"],
            "text": " ".join(map(str, d["symptoms"])) + " " + d["body"]} for d in DOCS]
FIELDS = ["short_description", "text"]
MIN_HYBRID = 0.85  # share of tickets whose first result is the right document

# (ticket text, acceptable documents for the first result)
CASES = [
    ("PC asks for a 48-digit code when I turn it on", {"KB-EP-001"}),
    ("I typed my password wrong too many times and now Windows won't let me in", {"KB-IAM-001", "RB-AD-001"}),
    ("Nobody hears me on calls, my headset mic seems dead", {"KB-M365-002"}),
    ("My laptop takes ages to boot and the fan is always loud", {"KB-EP-003"}),
    ("No space left, I can't save anything on my computer", {"KB-EP-002"}),
    ("I need permission to open the finance team's network drive", {"KB-IAM-004"}),
    ("I press print and nothing comes out, documents wait forever", {"KB-PRN-001"}),
    ("Got a new phone and I can't approve sign-in requests anymore", {"KB-IAM-003"}),
    ("Big workbook makes the spreadsheet program shut down", {"KB-M365-004"}),
    ("Wireless says connected, but no web page loads", {"KB-NET-002"}),
    ("Error 809 when I connect from the hotel", {"KB-NET-001"}),
    ("intranet.helios.local says server not found but Google works", {"KB-NET-003"}),
    ("Back from holiday and my password has expired", {"KB-IAM-002"}),
    ("The team mailbox disappeared from my Outlook", {"KB-M365-005"}),
    ("OneDrive shows a red X on my project folder", {"KB-M365-003"}),
    ("When I present in Zoom people only see black", {"KB-EP-004"}),
    ("SAP logon says partner not reached", {"KB-APP-001"}),
    ("Outlook asks for my credentials every five minutes", {"KB-M365-001"}),
    ("APP01 /var at 95%, the application can't write its logs", {"RB-SRV-001"}),
    ("Portal returns 502 bad gateway on APP02", {"RB-SRV-002"}),
    ("Monitoring alert: C: drive on FS01 has 3% free", {"RB-SRV-003"}),
    ("portal.helios.local certificate expires in 10 days", {"RB-SRV-004"}),
    ("Last night's backup of FS01 failed", {"RB-SRV-005"}),
    ("Nobody on the 3rd floor can print, every queue on PRT01 is stuck", {"RB-PRN-001"}),
    ("User locked out again right after we unlocked him, event 4740", {"RB-AD-002"}),
    ("Password changes are not applied on all domain controllers", {"RB-AD-003"}),
    ("The whole Milan office can't connect to the VPN", {"RB-NET-001"}),
    ("Unlock the AD account of jdoe, identity verified", {"RB-AD-001"}),
    # exact commands and names engineers type: where the full-text part of hybrid search earns its place
    ("repadmin shows errors", {"RB-AD-003"}),
    ("PanGPS service keeps stopping", {"KB-NET-001"}),
    ("klist purge did not help", {"KB-IAM-004"}),
    ("SAPUILandscape.xml is outdated", {"KB-APP-001"}),
    ("MicrosoftOffice16_Data entries", {"KB-M365-001"}),
    ("journalctl is huge", {"RB-SRV-001"}),
    ("StartComponentCleanup failed", {"RB-SRV-003"}),
    ("Temporary Access Pass needed", {"KB-IAM-003"}),
    ("FS_Finance_RW group", {"KB-IAM-004"}),
    ("LockoutStatus tool", {"KB-IAM-001", "RB-AD-002"}),
    ("dcdiag dns test fails", {"RB-AD-003"}),
    ("Unlock-ADAccount", {"RB-AD-001"}),
]


def evaluate(name, search):
    hits = 0
    for text, expected in CASES:
        found = search(text)
        ok = bool(found) and found[0] in expected
        hits += ok
        if not ok:
            print(f"  {name} miss: {text!r} -> {found[:1] or 'nothing'} (expected {sorted(expected)})")
    return hits / len(CASES)


def main():
    from jarvis.semantic import MODEL, SemanticIndex
    semantic = SemanticIndex()
    scores = {
        "keyword": evaluate("keyword", lambda t: [r["number"] for r in rank(RECORDS, keywords(t), FIELDS, 1)]),
        "semantic": evaluate("semantic", lambda t: [r["number"] for r in semantic.top(t, RECORDS, FIELDS, 1)]),
    }
    if os.getenv("TEST_DATABASE_URL"):
        from jarvis.db import connect
        from jarvis.knowledge import KnowledgeBase
        kb = KnowledgeBase(connect(os.environ["TEST_DATABASE_URL"]), semantic.embedder, MODEL)
        kb.ingest(DOCS)
        scores["hybrid"] = evaluate("hybrid", lambda t: [r["doc_id"] for r in kb.search(t, 1)])
    print(f"\nRight document first, {len(CASES)} tickets: " + ", ".join(f"{k} {v:.0%}" for k, v in scores.items()))
    if "hybrid" in scores and scores["hybrid"] < MIN_HYBRID:
        sys.exit(f"hybrid retrieval {scores['hybrid']:.0%} is below the {MIN_HYBRID:.0%} gate")
    return scores


if __name__ == "__main__":
    main()
