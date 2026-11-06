"""Minimal ServiceNow Table API client."""
import functools
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


# Prefix of the work note the "Unlock account (Jarvis)" button writes: Jarvis acts only after finding it
APPROVAL = "Approved Jarvis action: unlock"


class Snow:
    def __init__(self, instance, user, password):
        self.base = instance.rstrip("/") + "/api/now/table/"
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
                          ["sys_id", "number", "short_description", "description", "category", "assignment_group", "caller_id"], limit)

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

    def approved(self, incident_sys_id):
        return bool(self.first("sys_journal_field",
                               f"element=work_notes^element_id={incident_sys_id}^valueSTARTSWITH{APPROVAL}"))

    def get_incident(self, sys_id):
        return self.first("incident", f"sys_id={sys_id}")

    def _search(self, table, base_query, fields, search_fields, text, top):
        # shortcut: LIKE match + local keyword ranking; switch to embeddings/vector search when the KB has thousands of articles
        words = keywords(text)
        if not words:
            return []
        like = "^OR".join(f"{f}LIKE{w}" for w in words for f in search_fields)
        return rank(self.query(table, f"{base_query}^{like}", fields, limit=50), words, search_fields, top)

    def search_kb(self, text, top=3):
        return self._search("kb_knowledge", "workflow_state=published", ["number", "short_description", "text"],
                            ["short_description", "text"], text, top)

    def kb_candidates(self, text, top=3):
        """Published articles and drafts: a draft already waiting for review also counts as coverage."""
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

    def add_work_note(self, sys_id, note, fields=None):
        self.update("incident", sys_id, {"work_notes": note, **(fields or {})})
