-- Phase 5: agents rate Jarvis's suggestions. One vote per agent and ticket; voting again changes it.
CREATE TABLE feedback (
    id              bigserial   PRIMARY KEY,
    ticket          text        NOT NULL,
    incident_sys_id text        NOT NULL,
    suggestion_id   bigint      REFERENCES suggestion (id),
    agent           text        NOT NULL,             -- ServiceNow user name, read from the agent's own work note
    helpful         boolean     NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (incident_sys_id, agent)
);
