"""PostgreSQL + pgvector: migrations, persistent embedding cache, suggestion audit."""
import json
from pathlib import Path

import numpy as np
import psycopg

MIGRATIONS = Path(__file__).parent.parent / "db" / "migrations"


def connect(url):
    # shortcut: one autocommit connection shared by the server threads (psycopg serializes them); use a pool under load
    conn = psycopg.connect(url, autocommit=True)
    migrate(conn)
    return conn


def migrate(conn):
    """Apply db/migrations/*.sql in name order, each once and in its own transaction."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.name not in done:
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            print(f"db: applied {f.name}")


def to_pg(vec):
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


class VectorStore:
    """Persistent cache for SemanticIndex: (sys_id, updated_on) -> (title vector, full-text vector)."""

    def __init__(self, conn, model):
        self.conn, self.model = conn, model

    def load(self, keys):
        if not keys:
            return {}
        rows = self.conn.execute(
            "SELECT sys_id, updated_on, kind, embedding::text FROM embedding_cache "
            "WHERE model = %s AND (sys_id, updated_on) IN (SELECT * FROM unnest(%s::text[], %s::text[]))",
            (self.model, [k[0] for k in keys], [str(k[1]) for k in keys])).fetchall()
        found = {}
        for sys_id, updated_on, kind, emb in rows:
            found.setdefault((sys_id, updated_on), {})[kind] = np.array(json.loads(emb))
        return {k: (v["title"], v["full"]) for k, v in found.items() if len(v) == 2}

    def save(self, vectors):
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO embedding_cache (sys_id, updated_on, kind, model, embedding) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                [(k[0], str(k[1]), kind, self.model, to_pg(vec))
                 for k, pair in vectors.items() for kind, vec in zip(("title", "full"), pair)])


def record_suggestion(conn, ticket, kind, model=None, sources=(), detail=None):
    conn.execute("INSERT INTO suggestion (ticket, kind, model, sources, detail) VALUES (%s, %s, %s, %s, %s)",
                 (ticket, kind, model, json.dumps(list(sources)), json.dumps(detail or {})))


class Executions:
    """Audit trail and state of procedure runs (table execution)."""

    def __init__(self, conn):
        self.conn = conn

    def record_auto(self, incident, procedure_id, params, result):
        """An L0 check Jarvis ran by itself."""
        self.conn.execute(
            "INSERT INTO execution (ticket, incident_sys_id, procedure_id, risk, params, status, approved_by, result, finished_at) "
            "VALUES (%s, %s, %s, 'L0', %s, %s, 'automatic', %s, now())",
            (incident["number"], incident["sys_id"], procedure_id, json.dumps(params),
             "failed" if result.get("error") else "succeeded", json.dumps(result)))

    def propose(self, incident, procedure_id, risk, params):
        """A new proposal replaces any older one still waiting on the same incident."""
        with self.conn.transaction():
            self.conn.execute("UPDATE execution SET status = 'superseded', finished_at = now() "
                              "WHERE incident_sys_id = %s AND status = 'proposed'", (incident["sys_id"],))
            return self.conn.execute(
                "INSERT INTO execution (ticket, incident_sys_id, procedure_id, risk, params, status) "
                "VALUES (%s, %s, %s, %s, %s, 'proposed') RETURNING id",
                (incident["number"], incident["sys_id"], procedure_id, risk, json.dumps(params))).fetchone()[0]

    def pending(self, incident_sys_id):
        row = self.conn.execute(
            "SELECT id, procedure_id, params FROM execution WHERE incident_sys_id = %s AND status = 'proposed' "
            "ORDER BY id DESC LIMIT 1", (incident_sys_id,)).fetchone()
        return {"id": row[0], "procedure_id": row[1], "params": row[2]} if row else None

    def get(self, execution_id):
        row = self.conn.execute(
            "SELECT id, ticket, incident_sys_id, procedure_id, risk, params, status, change_number FROM execution WHERE id = %s",
            (execution_id,)).fetchone()
        keys = ("id", "ticket", "incident_sys_id", "procedure_id", "risk", "params", "status", "change_number")
        return dict(zip(keys, row)) if row else None

    def set_change(self, execution_id, change_number):
        self.conn.execute("UPDATE execution SET change_number = %s WHERE id = %s", (change_number, execution_id))

    def finish(self, execution_id, status, approved_by=None, result=None, verify_result=None):
        self.conn.execute(
            "UPDATE execution SET status = %s, approved_by = %s, result = %s, verify_result = %s, finished_at = now() "
            "WHERE id = %s",
            (status, approved_by, json.dumps(result) if result is not None else None,
             json.dumps(verify_result) if verify_result is not None else None, execution_id))
