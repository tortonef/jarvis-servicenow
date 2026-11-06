"""SemanticIndex logic with a fake embedder (no model download). Real-model quality: python -m tests.eval_search"""
import unittest

import numpy as np

from jarvis.semantic import SemanticIndex

VOCAB = ["vpn", "printer", "teams", "filler"]


class FakeEmbedder:
    """One dimension per vocabulary word, normalized: cosine = shared-word overlap."""
    def __init__(self):
        self.embedded = []

    def _vec(self, text):
        v = np.array([text.lower().count(w) for w in VOCAB], dtype=float)
        return v / (np.linalg.norm(v) or 1)

    def embed(self, texts):
        self.embedded += texts
        return [self._vec(t) for t in texts]

    def query_embed(self, texts):
        return [self._vec(t) for t in texts]


RECORDS = [
    {"sys_id": "1", "sys_updated_on": "a", "short_description": "VPN error", "text": "<p>vpn</p>"},
    {"sys_id": "2", "sys_updated_on": "a", "short_description": "Printer queue", "text": "<p>printer</p>"},
    # title is on point, body is mostly about something else: best-of scoring must still find it
    {"sys_id": "3", "sys_updated_on": "a", "short_description": "Teams audio", "text": "filler " * 20},
]
FIELDS = ["short_description", "text"]


class TestSemantic(unittest.TestCase):
    def test_ranks_by_meaning_and_drops_unrelated(self):
        idx = SemanticIndex(FakeEmbedder())
        self.assertEqual([r["sys_id"] for r in idx.top("my vpn is down", RECORDS, FIELDS)], ["1"])
        self.assertEqual(idx.top("coffee machine broken", RECORDS, FIELDS), [])

    def test_title_counts_even_when_body_dilutes_it(self):
        idx = SemanticIndex(FakeEmbedder())
        self.assertEqual(idx.top("teams", RECORDS, FIELDS)[0]["sys_id"], "3")

    def test_embeds_only_new_or_edited_records(self):
        emb = FakeEmbedder()
        idx = SemanticIndex(emb)
        idx.top("vpn", RECORDS, FIELDS)
        first = len(emb.embedded)
        idx.top("printer", RECORDS, FIELDS)
        self.assertEqual(len(emb.embedded), first)          # cache hit
        edited = [dict(RECORDS[0], sys_updated_on="b")] + RECORDS[1:]
        idx.top("vpn", edited, FIELDS)
        self.assertEqual(len(emb.embedded), first + 2)      # title + full text of the edited record only

    def test_empty_records(self):
        self.assertEqual(SemanticIndex(FakeEmbedder()).top("vpn", [], FIELDS), [])


if __name__ == "__main__":
    unittest.main()
