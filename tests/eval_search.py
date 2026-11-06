"""Keyword vs semantic search on the demo KB, with tickets phrased the way users write them (offline).

Usage: python -m tests.eval_search
"""
import json
from pathlib import Path

from jarvis.semantic import SemanticIndex
from jarvis.snow import keywords, rank

KB = json.loads((Path(__file__).parent.parent / "seed" / "kb_articles.json").read_text(encoding="utf-8"))
KB = [{"sys_id": str(i), "number": f"KB{i:02}", **a} for i, a in enumerate(KB)]
FIELDS = ["short_description", "text"]

# (ticket text, a word that must appear in the right article's title)
CASES = [
    ("PC asks for a 48-digit code when I turn it on", "BitLocker"),
    ("I typed my password wrong too many times and now Windows won't let me in", "locked out"),
    ("Nobody hears me on calls, my headset mic seems dead", "Teams"),
    ("My laptop takes ages to boot and the fan is always loud", "Slow laptop"),
    ("No space left, I can't save anything on my computer", "drive full"),
    ("I need permission to open the finance team's network drive", "shared folder"),
    ("I press print and nothing comes out, documents wait forever", "printer"),
    ("Got a new phone and I can't approve sign-in requests anymore", "MFA"),
    ("Big workbook makes the spreadsheet program shut down", "Excel"),
    ("Wireless says connected, but no web page loads", "Wi-Fi"),
]


def main():
    semantic = SemanticIndex()
    hits = {"keyword": 0, "semantic": 0}
    print(f"{'ticket':<80} keyword  semantic")
    for text, expected in CASES:
        kw = rank(KB, keywords(text), FIELDS, 1)
        sem = semantic.top(text, KB, FIELDS, 1)
        ok = {name: bool(r) and expected.lower() in r[0]["short_description"].lower()
              for name, r in (("keyword", kw), ("semantic", sem))}
        for name in hits:
            hits[name] += ok[name]
        print(f"{text[:78]:<80} {'yes' if ok['keyword'] else 'no':<8} {'yes' if ok['semantic'] else 'no'}")
    print(f"\nRight article first: keyword {hits['keyword']}/{len(CASES)}, semantic {hits['semantic']}/{len(CASES)}")
    return hits


if __name__ == "__main__":
    main()
