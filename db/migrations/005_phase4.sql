-- Phase 4: L2 procedures run through an approved Change, and the self-service portal.
ALTER TABLE execution ADD COLUMN change_number text;   -- the Change an L2 procedure waits for

CREATE TABLE self_service (
    id          bigserial   PRIMARY KEY,
    user_name   text        NOT NULL,
    question    text        NOT NULL,
    answer      text        NOT NULL,
    sources     jsonb       NOT NULL DEFAULT '[]',
    solved      boolean,                               -- null until the user says
    incident    text,                                  -- the ticket opened when it did not help
    created_at  timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz
);
