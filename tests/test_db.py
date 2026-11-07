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

    def test_knowledge_ingest_detects_changes_and_searches(self):
        from jarvis.knowledge import KnowledgeBase, parse
        from tests.test_knowledge import GOOD
        from tests.test_semantic import FakeEmbedder
        vpn = parse("articles/vpn.md", GOOD.replace("Test article", "VPN error").replace("Step one", "vpn step"))
        printer = parse("articles/prn.md", GOOD.replace("KB-NET-901", "KB-PRN-901").replace("Test article", "Printer queue")
                        .replace("vpn down", "printer jammed"))
        emb = FakeEmbedder()
        kb = KnowledgeBase(self.conn, emb, "fake")
        kb.ingest([])  # start empty: the eval may have loaded the real knowledge base into this database
        changed, removed = kb.ingest([vpn, printer], "sha1")
        self.assertEqual(({d["id"] for d in changed}, removed), ({"KB-NET-901", "KB-PRN-901"}, []))
        self.assertEqual(kb.state(), "sha1")
        calls = len(emb.embedded)
        self.assertEqual(kb.ingest([vpn, printer])[0], [])               # unchanged: nothing re-embedded
        self.assertEqual(len(emb.embedded), calls)
        self.assertEqual(kb.search("printer is jammed", 1)[0]["doc_id"], "KB-PRN-901")
        self.assertEqual(kb.search("coffee", 1), [])                     # unrelated: below the threshold
        kb.set_kb_number("KB-NET-901", "KB0010050")
        self.assertEqual([d["id"] for d in kb.unpublished([vpn, printer])], ["KB-PRN-901"])
        self.assertEqual(kb.search("vpn", 1)[0]["number"], "KB0010050")  # cites the ServiceNow article
        changed, removed = kb.ingest([vpn])                               # printer doc deleted from the repo
        self.assertEqual((changed, removed), ([], ["KB-PRN-901"]))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM chunk WHERE document_id = 'KB-PRN-901'").fetchone()[0], 0)
        kb.ingest([])

    @classmethod
    def tearDownClass(cls):
        cls.conn.execute("DELETE FROM embedding_cache WHERE model IN ('test-model', 'fake')")
        cls.conn.execute("DELETE FROM suggestion WHERE ticket = 'INC-TEST'")
        cls.conn.close()


if __name__ == "__main__":
    unittest.main()
