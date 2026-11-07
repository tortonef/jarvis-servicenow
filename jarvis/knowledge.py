"""Docs as code: load, validate and chunk the Helios knowledge base, ingest it into PostgreSQL, search it, and
publish it to the ServiceNow KB.

Usage:
    python -m jarvis.knowledge check [folder]   validate front matter (CI runs this)
    python -m jarvis.knowledge sync             ingest + publish from DOCS_DIR or DOCS_REPO once
"""
import datetime
import hashlib
import html
import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path

import numpy as np
import yaml

from jarvis.snow import keywords

FOLDERS = {"articles": ("article", "KB"), "runbooks": ("runbook", "RB")}
REQUIRED = {"id": str, "title": str, "audience": list, "systems": list, "symptoms": list, "owner": str,
            "review_by": datetime.date}
ID_RE = re.compile(r"^(KB|RB)-[A-Z0-9]+-\d{3}$")
DOC_PATH = re.compile(r"^(?:[^/]+/)?knowledge/(articles|runbooks)/([\w.-]+\.md)$")  # local or inside a GitHub tarball
MAX_DOC_BYTES = 200_000
MIN_SCORE = 0.6    # same scale as jarvis.semantic: below this the document is not about the ticket
KEYWORD_WEIGHT = 0.15  # meaning leads; full text rescues exact commands and codes (eval: 0 and 0.15 tie on user
#                        tickets, 0.15 wins on command names, 0.3+ starts to hurt)


# ---------- loading ----------

def parse(path, text):
    """One Markdown file with YAML front matter -> document dict. Raises ValueError on a malformed file."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path}: missing front matter")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: invalid front matter: {e}".replace("\n", " ")) from None
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: front matter must be a mapping")
    folder = path.split("/")[-2]
    kind = FOLDERS.get(folder, (None,))[0]
    return {**meta, "kind": kind, "path": path, "body": m.group(2).strip(), "hash": hashlib.sha256(text.encode()).hexdigest()}


def load_dir(root):
    root = Path(root)
    return [parse(f"{folder}/{f.name}", f.read_text(encoding="utf-8"))
            for folder in FOLDERS for f in sorted((root / folder).glob("*.md"))]


def load_tarball(data):
    """Documents from a GitHub tarball, read in memory: nothing is extracted to disk, so archive paths can't escape."""
    docs = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            m = DOC_PATH.match(member.name)
            if member.isfile() and m and member.size <= MAX_DOC_BYTES:
                docs.append(parse(f"{m.group(1)}/{m.group(2)}", tar.extractfile(member).read().decode("utf-8")))
    return sorted(docs, key=lambda d: d["path"])


def fetch_github(repo, ref="main", known_sha=None):
    """(commit sha, documents) for repo@ref, or (sha, None) when the commit is the one already ingested."""
    import requests
    r = requests.get(f"https://api.github.com/repos/{repo}/commits/{ref}", timeout=30,
                     headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    sha = r.json()["sha"]
    if sha == known_sha:
        return sha, None
    tar = requests.get(f"https://codeload.github.com/{repo}/tar.gz/{sha}", timeout=60)
    tar.raise_for_status()
    return sha, load_tarball(tar.content)


# ---------- validation ----------

def check(docs):
    """List of problems; empty means every document can be published."""
    errors, seen = [], {}
    for d in docs:
        where = d["path"]
        if d["kind"] is None:
            errors.append(f"{where}: must live in articles/ or runbooks/")
            continue
        for key, typ in REQUIRED.items():
            if not isinstance(d.get(key), typ):
                errors.append(f"{where}: '{key}' missing or not a {typ.__name__}")
        doc_id = d.get("id")
        if isinstance(doc_id, str):
            prefix = FOLDERS[d["path"].split("/")[0]][1]
            if not ID_RE.match(doc_id) or not doc_id.startswith(prefix + "-"):
                errors.append(f"{where}: id '{doc_id}' must look like {prefix}-AREA-001")
            if doc_id in seen:
                errors.append(f"{where}: id '{doc_id}' already used by {seen[doc_id]}")
            seen[doc_id] = where
        if "## " not in d["body"]:
            errors.append(f"{where}: body needs at least one '## ' section")
    return errors


# ---------- shaping ----------

def chunks(doc):
    """A title chunk (title + how users describe the problem) plus one chunk per '## ' section."""
    head = f"{doc['title']}\nSymptoms: {', '.join(map(str, doc['symptoms']))}"
    sections = [s.strip() for s in re.split(r"(?m)^## ", doc["body"]) if s.strip()]
    return [head] + [f"{doc['title']} - {s}"[:2000] for s in sections]


def _inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<em>\1</em>", text)


def to_html(doc):
    """The Markdown subset the docs use (## headings, lists, paragraphs, inline code, bold, italic) as KB HTML."""
    out, lst = [], None
    for line in doc["body"].splitlines():
        item = re.match(r"^(\d+)\.\s+(.*)$|^-\s+(.*)$", line)
        if item:
            tag = "ol" if item.group(1) else "ul"
            if lst != tag:
                out.append(f"</{lst}>" if lst else "")
                out.append(f"<{tag}>")
                lst = tag
            out.append(f"<li>{_inline(item.group(2) or item.group(3))}</li>")
            continue
        if lst and line.startswith("   ") and line.strip():  # continuation of the previous list item
            out[-1] = out[-1][:-5] + "<br>" + _inline(line.strip()) + "</li>"
            continue
        if lst:
            out.append(f"</{lst}>")
            lst = None
        if line.startswith("## "):
            out.append(f"<h3>{_inline(line[3:])}</h3>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
    if lst:
        out.append(f"</{lst}>")
    out.append(f"<p><em>Source: {html.escape(doc['id'])} in the Helios docs repository. Edit it there, not here.</em></p>")
    return "".join(out)


# ---------- PostgreSQL ----------

class KnowledgeBase:
    def __init__(self, conn, embedder, model):
        self.conn, self.embedder, self.model = conn, embedder, model

    def state(self):
        row = self.conn.execute("SELECT value FROM knowledge_state WHERE key = 'commit_sha'").fetchone()
        return row[0] if row else None

    def ingest(self, docs, commit_sha=None):
        """Upsert changed documents with their chunks, delete removed ones. Returns (changed docs, removed ids)."""
        from jarvis.db import to_pg
        known = dict(self.conn.execute("SELECT id, content_hash || ':' || embedding_model FROM document").fetchall())
        changed = [d for d in docs if known.get(d["id"]) != f"{d['hash']}:{self.model}"]
        removed = sorted(set(known) - {d["id"] for d in docs})
        with self.conn.transaction():
            for doc_id in removed:
                self.conn.execute("DELETE FROM document WHERE id = %s", (doc_id,))
            for d in changed:
                texts = chunks(d)
                vecs = list(self.embedder.embed(texts))
                self.conn.execute(
                    "INSERT INTO document (id, kind, title, audience, systems, owner, review_by, path, body, content_hash, "
                    "embedding_model, commit_sha) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET kind = EXCLUDED.kind, title = EXCLUDED.title, audience = EXCLUDED.audience, "
                    "systems = EXCLUDED.systems, owner = EXCLUDED.owner, review_by = EXCLUDED.review_by, path = EXCLUDED.path, "
                    "body = EXCLUDED.body, content_hash = EXCLUDED.content_hash, embedding_model = EXCLUDED.embedding_model, "
                    "commit_sha = EXCLUDED.commit_sha, updated_at = now()",
                    (d["id"], d["kind"], d["title"], [str(a) for a in d["audience"]], [str(s) for s in d["systems"]],
                     d["owner"], d["review_by"], d["path"], d["body"], d["hash"], self.model, commit_sha))
                self.conn.execute("DELETE FROM chunk WHERE document_id = %s", (d["id"],))
                with self.conn.cursor() as cur:
                    cur.executemany("INSERT INTO chunk (document_id, ord, content, embedding) VALUES (%s, %s, %s, %s)",
                                    [(d["id"], i, t, to_pg(v)) for i, (t, v) in enumerate(zip(texts, vecs))])
            if commit_sha:
                self.conn.execute("INSERT INTO knowledge_state (key, value) VALUES ('commit_sha', %s) "
                                  "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (commit_sha,))
        return changed, removed

    def search(self, text, top=3):
        """Hybrid search: meaning (pgvector cosine) plus a small full-text bonus for exact words and error codes.
        Returns records shaped like ServiceNow KB rows, so the prompt code stays the same."""
        from jarvis.db import to_pg
        q = to_pg(np.asarray(next(iter(self.embedder.query_embed([text])))))
        terms = " | ".join(keywords(text, max_words=12))
        rows = self.conn.execute(
            "SELECT d.id, d.kb_number, d.title, d.body, "
            "max(1 - (c.embedding <=> %(q)s::vector) + %(w)s * least(1, ts_rank_cd(c.fts, to_tsquery('english', %(t)s)))) AS score "
            "FROM chunk c JOIN document d ON d.id = c.document_id "
            "GROUP BY d.id ORDER BY score DESC LIMIT %(k)s",
            {"q": q, "t": terms or "''", "w": KEYWORD_WEIGHT if terms else 0, "k": top}).fetchall()
        return [{"number": kb or doc_id, "doc_id": doc_id, "short_description": title, "text": body, "score": float(s)}
                for doc_id, kb, title, body, s in rows if s >= MIN_SCORE]

    def unpublished(self, docs):
        """Documents ServiceNow does not have yet (new, changed, or a previous sync failed)."""
        numbers = dict(self.conn.execute("SELECT id, kb_number FROM document").fetchall())
        return [d for d in docs if not numbers.get(d["id"])]

    def set_kb_number(self, doc_id, number):
        self.conn.execute("UPDATE document SET kb_number = %s WHERE id = %s", (number, doc_id))


# ---------- ServiceNow ----------

def publish(snow, kb, docs, removed, kb_title):
    """Create, update and publish articles through the Jarvis KB API (the Table API can't edit published articles)."""
    op = snow.first("sys_ws_operation", "web_service_definition.service_id=jarvis_kb^relative_path=/articles")
    if not op:
        raise RuntimeError("Jarvis KB API missing in ServiceNow: run python -m seed.install_snow")
    url = snow.instance + op["operation_uri"]
    for d in docs:
        r = snow.http.post(url, timeout=60, json={"doc_id": d["id"], "kb": kb_title, "title": d["title"],
                                                  "html": to_html(d), "keywords": " ".join(map(str, d["symptoms"]))})
        r.raise_for_status()
        kb.set_kb_number(d["id"], r.json()["result"]["number"])
        print(f"knowledge: {d['id']} -> {r.json()['result']['number']}")
    for doc_id in removed:
        snow.http.post(url, timeout=60, json={"doc_id": doc_id, "kb": kb_title, "retire": True}).raise_for_status()
        print(f"knowledge: {doc_id} retired")


def sync(snow, kb, kb_title, force=False):
    """Ingest the configured docs source and publish what changed. Returns the number of documents touched.
    force=True (startup) re-reads the source even on a known commit, so articles a failed sync left unpublished
    are retried; unchanged documents are skipped by hash either way."""
    try:
        if os.getenv("DOCS_DIR"):
            docs, sha = load_dir(os.environ["DOCS_DIR"]), None
        else:
            sha, docs = fetch_github(os.environ["DOCS_REPO"], os.getenv("DOCS_REF", "main"), None if force else kb.state())
            if docs is None:
                return 0
    except ValueError as e:  # a malformed file: keep serving the last good knowledge base
        print(f"knowledge: not synced: {e}")
        return 0
    errors = check(docs)
    if errors:  # never publish a broken knowledge base; keep serving the last good one
        print("knowledge: not synced, invalid documents:\n  " + "\n  ".join(errors))
        return 0
    changed, removed = kb.ingest(docs, sha)
    todo = {d["id"]: d for d in changed + kb.unpublished(docs)}
    publish(snow, kb, list(todo.values()), removed, kb_title)
    print(f"knowledge: {len(docs)} documents, {len(changed)} changed, {len(removed)} removed"
          + (f", commit {sha[:7]}" if sha else ""))
    return len(todo) + len(removed)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "check":
        root = sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent.parent / "knowledge"
        try:
            docs = load_dir(root)
        except ValueError as e:
            raise SystemExit(str(e))
        errors = check(docs)
        print("\n".join(errors) or f"{len(docs)} documents OK")
        sys.exit(1 if errors else 0)
    if len(sys.argv) == 2 and sys.argv[1] == "sync":
        from jarvis.config import KB_TITLE, snow_from_env
        snow = snow_from_env()
        if not snow.knowledge:
            raise SystemExit("sync needs DATABASE_URL and SEARCH=semantic")
        sync(snow, snow.knowledge, KB_TITLE, force=True)
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
