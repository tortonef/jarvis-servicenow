"""Procedure catalog and policy: which procedures fit a ticket, with which parameters, and when an L1 may be proposed.

The model never chooses or writes an action. Procedures come from procedures/catalog.yaml, they are linked to the
knowledge documents retrieval found, parameters come from ServiceNow data (the caller) or from a fixed list of values
named in the ticket, and proposals and verifications are rules on read-only (L0) results.

Usage: python -m jarvis.procedures check
"""
import functools
import re
import sys
from pathlib import Path

import yaml

from jarvis import mid

CATALOG = Path(__file__).parent.parent / "procedures" / "catalog.yaml"
RISKS = ("L0", "L1", "L2")
OPERATORS = {"equals": lambda a, b: a == b, "at_least": lambda a, b: a is not None and a >= b,
             "below": lambda a, b: a is not None and a < b}


@functools.cache
def load(path=CATALOG):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def check(catalog):
    """List of problems; empty means the catalog is safe to load."""
    errors = []
    for pid, p in catalog.items():
        where = f"procedure {pid}"
        if not isinstance(p, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        if p.get("risk") not in RISKS:
            errors.append(f"{where}: risk must be one of {RISKS}")
        if not p.get("title") or not isinstance(p.get("docs"), list) or not p["docs"]:
            errors.append(f"{where}: needs a title and at least one doc")
        call = (p.get("mid") or {}).get("call")
        if call not in mid.CALLS:
            errors.append(f"{where}: mid.call must be one of {sorted(mid.CALLS)}")
        if call == "ssh" and not (p.get("mid") or {}).get("verb"):
            errors.append(f"{where}: ssh procedures need mid.verb")
        for name, spec in (p.get("params") or {}).items():
            if not isinstance(spec, dict) or spec.get("from") not in ("caller", "ticket"):
                errors.append(f"{where}: param {name} needs from: caller or ticket")
            elif not (spec.get("pattern") or spec.get("enum")):
                errors.append(f"{where}: param {name} needs a pattern or an enum")  # nothing unvalidated reaches the MID
        if p.get("risk") in ("L1", "L2") and not (p.get("propose_if") and p.get("verify")):
            errors.append(f"{where}: L1 and L2 procedures need propose_if and verify")
        for key in ("propose_if", "verify"):
            cond = p.get(key)
            if cond is None:
                continue
            target = catalog.get(cond.get("check")) if isinstance(cond, dict) else None
            if not target or target.get("risk") != "L0":
                errors.append(f"{where}: {key}.check must name an L0 procedure")
            elif not any(op in cond for op in OPERATORS) or "field" not in cond:
                errors.append(f"{where}: {key} needs a field and one of {sorted(OPERATORS)}")
    return errors


def resolve(proc, incident, caller):
    """Parameters for this ticket, or None when one can't be determined unambiguously."""
    text = f"{incident.get('short_description', '')} {incident.get('description', '')}".lower()
    params = {}
    for name, spec in (proc.get("params") or {}).items():
        if spec["from"] == "caller":
            value = (caller or {}).get("user_name")
        else:
            found = [v for v in spec["enum"] if re.search(rf"\b{re.escape(str(v).lower())}\b", text)]
            value = found[0] if len(found) == 1 else None
        if value is None or not valid(spec, value):
            return None
        params[name] = value
    return params


def valid(spec, value):
    if "enum" in spec and value not in spec["enum"]:
        return False
    return not spec.get("pattern") or bool(re.fullmatch(spec["pattern"], str(value)))


def holds(cond, result):
    op = next(o for o in OPERATORS if o in cond)
    return bool(result) and not result.get("error") and OPERATORS[op](result.get(cond["field"]), cond[op])


def for_docs(catalog, doc_ids):
    """Procedures linked to the documents retrieval returned, in catalog order."""
    return [pid for pid, p in catalog.items() if set(p["docs"]) & set(doc_ids)]


def run(snow, proc, params):
    """Execute one procedure on-prem through the MID Server; returns its JSON result."""
    extra = {"verb": proc["mid"]["verb"]} if proc["mid"].get("verb") else {}
    return mid.run(snow, proc["mid"]["call"], {**params, **extra})


def summary(result):
    """One readable line for a work note."""
    if result.get("error"):
        return f"failed: {result['error']}"
    return ", ".join(f"{k} {v}" for k, v in result.items() if k not in ("dn", "host", "account", "body"))


def main():
    if sys.argv[1:] != ["check"]:
        raise SystemExit(__doc__)
    errors = check(load())
    print("\n".join(errors) or f"{len(load())} procedures OK")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
