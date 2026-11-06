"""PostgreSQL + pgvector against a real database. Skipped unless TEST_DATABASE_URL is set (docker compose db, CI)."""
import os
import unittest

import numpy as np

URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(URL, "set TEST_DATABASE_URL to run the database tests")
class TestDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jarvis.db import connect
        cls.conn = connect(URL)

    def test_migrations_are_idempotent(self):
        from jarvis.db import migrate
        migrate(self.conn)  # second run applies nothing and does not fail
        names = [r[0] for r in self.conn.execute("SELECT name FROM schema_migrations")]
        self.assertEqual(names.count("001_init.sql"), 1)

    def test_vector_store_round_trip(self):
        from jarvis.db import VectorStore
        store = VectorStore(self.conn, "test-model")
        t, f = np.random.rand(384), np.random.rand(384)
        store.save({("sys-test", "2026-01-01"): (t, f)})
        store.save({("sys-test", "2026-01-01"): (t, f)})  # duplicate save is ignored
        loaded = store.load([("sys-test", "2026-01-01"), ("missing", "x")])
        self.assertEqual(list(loaded), [("sys-test", "2026-01-01")])
        np.testing.assert_allclose(loaded[("sys-test", "2026-01-01")][0], t, atol=1e-6)
        self.assertEqual(store.load([("sys-test", "2026-02-02")]), {})  # edited record: cache miss

    def test_semantic_index_reuses_stored_vectors(self):
        from jarvis.db import VectorStore
        from jarvis.semantic import SemanticIndex
        from tests.test_semantic import FIELDS, RECORDS, FakeEmbedder
        records = [dict(r, sys_id=f"db-{r['sys_id']}") for r in RECORDS]
        SemanticIndex(FakeEmbedder(), VectorStore(self.conn, "fake")).top("vpn", records, FIELDS)
        emb = FakeEmbedder()  # a new process: empty memory, same database
        hit = SemanticIndex(emb, VectorStore(self.conn, "fake")).top("vpn", records, FIELDS)
        self.assertEqual(emb.embedded, [])  # nothing re-embedded
        self.assertEqual(hit[0]["sys_id"], "db-1")

    def test_audit_row(self):
        from jarvis.db import record_suggestion
        record_suggestion(self.conn, "INC-TEST", "answer", "m", ["KB1"], {"triage": {}})
        row = self.conn.execute("SELECT kind, sources FROM suggestion WHERE ticket = 'INC-TEST' ORDER BY id DESC").fetchone()
        self.assertEqual(row, ("answer", ["KB1"]))

    @classmethod
    def tearDownClass(cls):
        cls.conn.execute("DELETE FROM embedding_cache WHERE model IN ('test-model', 'fake')")
        cls.conn.execute("DELETE FROM suggestion WHERE ticket = 'INC-TEST'")
        cls.conn.close()


if __name__ == "__main__":
    unittest.main()
