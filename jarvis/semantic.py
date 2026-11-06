"""Semantic ranking with local embeddings: finds the right article even when the ticket uses different words."""
import numpy as np

from jarvis.agent import strip_html

MODEL = "BAAI/bge-small-en-v1.5"
MIN_SCORE = 0.6  # below this a record is not about the ticket (bge-small cosine; unrelated IT texts score ~0.5-0.57)


class SemanticIndex:
    def __init__(self, embedder=None, store=None):
        """store: optional persistent cache with load(keys) -> {key: vectors} and save({key: vectors})."""
        if embedder is None:
            from fastembed import TextEmbedding  # imported lazily: keyword mode and tests do not need it
            embedder = TextEmbedding(MODEL)
        self.embedder, self.store, self.vectors = embedder, store, {}

    def top(self, query, records, fields, k=3):
        """Records ordered by similarity to the query. A record scores the best of its title (first field) and its
        full text: long bodies dilute the meaning (measured in tests/eval_search.py: 8/10 full text, 10/10 best-of).
        Vectors are cached per sys_id + last update (in memory, and in the store if any), so only new or edited
        records are embedded."""
        key = lambda r: (r["sys_id"], str(r.get("sys_updated_on", "")))
        if self.store:
            self.vectors.update(self.store.load([key(r) for r in records if key(r) not in self.vectors]))
        missing = list({key(r): r for r in records if key(r) not in self.vectors}.values())
        if missing:
            titles = [strip_html(str(r.get(fields[0], "")), 500) for r in missing]
            fulls = [" ".join(strip_html(str(r.get(f, "")), 2000) for f in fields) for r in missing]
            vecs = list(self.embedder.embed(titles + fulls))
            new = {key(r): (np.asarray(vecs[i]), np.asarray(vecs[len(missing) + i])) for i, r in enumerate(missing)}
            self.vectors.update(new)
            if self.store:
                self.store.save(new)
        if not records:
            return []
        q = np.asarray(next(iter(self.embedder.query_embed([query]))))
        score = lambda r: max(float(v @ q) for v in self.vectors[key(r)])
        scored = sorted(((score(r), r) for r in records), key=lambda x: -x[0])
        return [r for s, r in scored[:k] if s >= MIN_SCORE]
