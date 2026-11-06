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
