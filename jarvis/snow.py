"""Minimal ServiceNow Table API client."""
import functools
import os
import re

import requests

STOPWORDS = {"the", "and", "for", "with", "not", "can", "cannot", "from", "this", "that", "since", "when", "during", "after",
             "into", "but", "all", "any", "are", "was", "has", "have", "won", "don", "doesn", "isn", "keeps", "need", "urgently"}


def keywords(text, max_words=8):
    words = [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3 and w not in STOPWORDS]
    return list(dict.fromkeys(words))[:max_words]


def rank(records, words, fields, top=3):
    """Order records by how many query words appear in the given fields (first field = title, counts double); drop zero matches."""
    def score(r):
        title, body = str(r.get(fields[0], "")).lower(), " ".join(str(r.get(f, "")) for f in fields[1:]).lower()
        return sum(2 * (w in title) + (w in body) for w in words)
    scored = sorted(((score(r), r) for r in records), key=lambda x: -x[0])
    return [r for s, r in scored if s > 0][:top]


# Work note prefixes of the L1 procedure flow. ServiceNow shows the approve button while the latest of these notes is a
# proposal; Jarvis acts only when an approval note follows the latest proposal.
PROPOSAL = "[Jarvis] Proposed procedure"
APPROVAL = "Approved Jarvis procedure"
OUTCOME = "[Jarvis] Procedure"
CHANGE_REQUESTED = "[Jarvis] Change requested:"  # L2: approval happens on the Change, not with a button
FEEDBACK = "Jarvis feedback:"  # written by the rating buttons in the agent's name
SUGGESTION = "[Jarvis] Resolution suggestion"


class Snow:
    def __init__(self, instance, user, password, semantic=None, db=None, knowledge=None):
        self.semantic = semantic  # a SemanticIndex, or None for keyword search
        self.db = db              # a psycopg connection for the audit trail, or None
        self.knowledge = knowledge  # a KnowledgeBase (docs repo in PostgreSQL), or None to search the ServiceNow KB
        self.executions = None      # jarvis.db.Executions when a database is configured
        self.instance = instance.rstrip("/")
        self.base = self.instance + "/api/now/table/"
        self.http = requests.Session()
        self.http.auth = (user, password)
        self.http.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def query(self, table, query, fields=None, limit=20):
        params = {"sysparm_query": query, "sysparm_limit": limit, "sysparm_display_value": "false"}
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        r = self.http.get(self.base + table, params=params, timeout=30)
        r.raise_for_status()
        return r.json()["result"]

    def first(self, table, query):
        res = self.query(table, query, limit=1)
        return res[0] if res else None

    def create(self, table, data):
        r = self.http.post(self.base + table, json=data, timeout=30)
        r.raise_for_status()
        return r.json()["result"]

    def new_incidents(self, limit=20):
        return self.query("incident", "active=true^state=1^ORDERBYDESCsys_created_on",
                          ["sys_id", "number", "short_description", "description", "category", "assignment_group", "caller_id", "priority"], limit)

    # shortcut: cached for the process lifetime; restart Jarvis after adding categories or groups
    @functools.cache
    def triage_options(self):
        """Incident categories (value -> label) and the groups that already handle incidents (name -> sys_id)."""
        cats = {c["value"]: c["label"] for c in self.query(
            "sys_choice", "name=incident^element=category^inactive=false^language=en", ["value", "label"], 100)}
        r = self.http.get(self.base.replace("/table/", "/stats/") + "incident", timeout=30, params={
            "sysparm_group_by": "assignment_group", "sysparm_count": "true", "sysparm_query": "assignment_groupISNOTEMPTY"})
        r.raise_for_status()
        ids = ",".join(x["groupby_fields"][0]["value"] for x in r.json()["result"])
        groups = {g["name"]: g["sys_id"] for g in self.query("sys_user_group", f"sys_idIN{ids}", ["name", "sys_id"], 100)}
        return cats, groups

    def get_user(self, sys_id):
        return self.first("sys_user", f"sys_id={sys_id}")

    def latest_feedback(self, incident_sys_id):
        """(agent user name, helpful) from the newest rating note on the incident, or None."""
        note = self.query("sys_journal_field", f"element=work_notes^element_id={incident_sys_id}"
                                               f"^valueSTARTSWITH{FEEDBACK}^ORDERBYDESCsys_created_on",
                          ["value", "sys_created_by"], 1)
        if not note:
            return None
        verdict = note[0]["value"][len(FEEDBACK):].strip().lower()
        if not verdict.startswith(("helpful", "not helpful")):
            return None
        return note[0]["sys_created_by"], verdict.startswith("helpful")

    def approval_for_proposal(self, incident_sys_id):
        """User name of the agent who approved the latest proposal, or None. ServiceNow's own clock orders the notes."""
        notes = self.query("sys_journal_field",
                           f"element=work_notes^element_id={incident_sys_id}^valueSTARTSWITH{PROPOSAL}"
                           f"^ORvalueSTARTSWITH{APPROVAL}^ORvalueSTARTSWITH{OUTCOME}^ORDERBYDESCsys_created_on",
                           ["value", "sys_created_by"], 5)
        if len(notes) >= 2 and notes[0]["value"].startswith(APPROVAL) and notes[1]["value"].startswith(PROPOSAL):
            return notes[0]["sys_created_by"]
        return None

    def approvers(self, sys_id):
        """Display names of the people who approved a record (e.g. a Change)."""
        r = self.http.get(self.base + "sysapproval_approver", timeout=30, params={
            "sysparm_query": f"sysapproval={sys_id}^state=approved", "sysparm_fields": "approver",
            "sysparm_display_value": "true", "sysparm_limit": 20})
        r.raise_for_status()
        return sorted({a["approver"]["display_value"] for a in r.json()["result"] if a.get("approver")})

    def get(self, table, sys_id):
        return self.first(table, f"sys_id={sys_id}")

    def get_incident(self, sys_id):
        return self.first("incident", f"sys_id={sys_id}")

    def _search(self, table, base_query, fields, search_fields, text, top):
        if self.semantic:
            # shortcut: embeds the 500 most recent records in memory; use a vector DB or ServiceNow AI Search beyond that
            records = self.query(table, f"{base_query}^ORDERBYDESCsys_updated_on",
                                 fields + ["sys_id", "sys_updated_on"], limit=500)
            return self.semantic.top(text, records, search_fields, top)
        words = keywords(text)
        if not words:
            return []
        like = "^OR".join(f"{f}LIKE{w}" for w in words for f in search_fields)
        return rank(self.query(table, f"{base_query}^{like}", fields, limit=50), words, search_fields, top)

    def search_kb(self, text, top=3):
        if self.knowledge:
            return self.knowledge.search(text, top)
        return self._search("kb_knowledge", "workflow_state=published", ["number", "short_description", "text"],
                            ["short_description", "text"], text, top)

    def kb_candidates(self, text, top=3):
        """Published articles and drafts: a draft already waiting for review also counts as coverage."""
        if self.knowledge:  # shortcut: drafts Jarvis wrote in ServiceNow are not seen here; Phase 5 moves drafts to pull requests
            return self.knowledge.search(text, top)
        return self._search("kb_knowledge", "workflow_stateINpublished,draft", ["number", "short_description", "text"],
                            ["short_description", "text"], text, top)

    def draft_for(self, incident_sys_id):
        return self.first("kb_knowledge", f"source={incident_sys_id}")

    @functools.cache
    def kb_base(self, title):
        return self.first("kb_knowledge_base", f"title={title}")

    def similar_resolved(self, text, top=3):
        return self._search("incident", "stateIN6,7", ["number", "short_description", "description", "close_notes"],
                            ["short_description", "description"], text, top)

    def update(self, table, sys_id, data):
        r = self.http.patch(self.base + f"{table}/{sys_id}", json=data, timeout=30)
        r.raise_for_status()
        return r.json()["result"]

    def audit(self, ticket, kind, sources=(), detail=None):
        """Record what Jarvis suggested or did. Never blocks the ServiceNow update it describes."""
        if not self.db:
            return
        from jarvis.db import record_suggestion
        try:
            record_suggestion(self.db, ticket, kind, os.getenv("LLM_MODEL"), sources, detail)
        except Exception as e:
            print(f"{ticket}: audit failed: {e}")

    def add_work_note(self, sys_id, note, fields=None):
        self.update("incident", sys_id, {"work_notes": note, **(fields or {})})
