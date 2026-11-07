-- Phase 3: every procedure run, automatic (L0) or approved (L1), with its parameters, approver and verification.
CREATE TABLE execution (
    id              bigserial   PRIMARY KEY,
    ticket          text        NOT NULL,             -- INC number
    incident_sys_id text        NOT NULL,
    procedure_id    text        NOT NULL,             -- key in procedures/catalog.yaml
    risk            text        NOT NULL CHECK (risk IN ('L0', 'L1', 'L2')),
    params          jsonb       NOT NULL,
    status          text        NOT NULL CHECK (status IN ('proposed', 'succeeded', 'failed', 'not_needed', 'superseded')),
    approved_by     text,                             -- 'automatic' for L0, the agent's user name for L1
    result          jsonb,
    verify_result   jsonb,
    proposed_at     timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX execution_incident_idx ON execution (incident_sys_id, id DESC);
