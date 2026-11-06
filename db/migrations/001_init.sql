-- Phase 0: persistent embedding cache and an audit trail of what Jarvis suggested.
-- Phase 1 replaces embedding_cache with document/chunk tables fed from the docs repo.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE embedding_cache (
    sys_id      text        NOT NULL,          -- ServiceNow record (KB article or incident)
    updated_on  text        NOT NULL,          -- sys_updated_on: an edited record gets new vectors
    kind        text        NOT NULL CHECK (kind IN ('title', 'full')),
    model       text        NOT NULL,
    embedding   vector      NOT NULL,          -- no fixed size: the model column says which embedding it is
    PRIMARY KEY (sys_id, updated_on, kind, model)
);

CREATE TABLE suggestion (
    id          bigserial   PRIMARY KEY,
    ticket      text        NOT NULL,          -- incident number, e.g. INC0010027
    kind        text        NOT NULL CHECK (kind IN ('answer', 'kb_draft', 'kb_covered', 'remediation')),
    model       text,
    sources     jsonb       NOT NULL DEFAULT '[]',
    detail      jsonb       NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX suggestion_ticket_idx ON suggestion (ticket);
