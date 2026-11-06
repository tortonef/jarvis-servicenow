"""Minimal ServiceNow Table API client."""
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
                          ["sys_id", "number", "short_description", "description"], limit)

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

    def similar_resolved(self, text, top=3):
        return self._search("incident", "stateIN6,7", ["number", "short_description", "description", "close_notes"],
                            ["short_description", "description"], text, top)

    def update(self, table, sys_id, data):
        r = self.http.patch(self.base + f"{table}/{sys_id}", json=data, timeout=30)
        r.raise_for_status()
        return r.json()["result"]

    def add_work_note(self, sys_id, note):
        self.update("incident", sys_id, {"work_notes": note})
