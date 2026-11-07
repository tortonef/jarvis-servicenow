-- Phase 1: the knowledge base from the docs repository, chunked and embedded for hybrid search.
CREATE TABLE document (
    id              text        PRIMARY KEY,            -- KB-NET-001, RB-AD-001: stable, from front matter
    kind            text        NOT NULL CHECK (kind IN ('article', 'runbook')),
    title           text        NOT NULL,
    audience        text[]      NOT NULL,
    systems         text[]      NOT NULL,
    owner           text        NOT NULL,
    review_by       date        NOT NULL,
    path            text        NOT NULL,
    body            text        NOT NULL,
    content_hash    text        NOT NULL,               -- unchanged files are not re-embedded or re-published
    embedding_model text        NOT NULL,
    commit_sha      text,
    kb_number       text,                               -- the ServiceNow article it is published as
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chunk (
    id          bigserial PRIMARY KEY,
    document_id text      NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    ord         int       NOT NULL,                     -- 0 = title + symptoms, then one per section
    content     text      NOT NULL,
    fts         tsvector  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding   vector    NOT NULL                      -- shortcut: no ANN index; add HNSW past ~10k chunks
);
CREATE INDEX chunk_document_idx ON chunk (document_id);
CREATE INDEX chunk_fts_idx ON chunk USING gin (fts);

CREATE TABLE knowledge_state (
    key   text PRIMARY KEY,
    value text NOT NULL
);
