-- Phase 6: the Watcher. Backlog counts over time and the SLA alerts Jarvis raised (one per SLA and level).
CREATE TABLE backlog_snapshot (
    taken_at         timestamptz NOT NULL DEFAULT now(),
    priority         text        NOT NULL,
    state            text        NOT NULL,
    assignment_group text        NOT NULL,     -- display name, '' when unassigned
    open             integer     NOT NULL,
    at_risk          integer     NOT NULL DEFAULT 0,  -- active SLAs at or above SLA_WARN_PERCENT, not yet breached
    breached         integer     NOT NULL DEFAULT 0
);
CREATE INDEX backlog_snapshot_taken_idx ON backlog_snapshot (taken_at);

CREATE TABLE sla_alert (
    task_sla_sys_id  text        NOT NULL,
    level            text        NOT NULL CHECK (level IN ('warning', 'breached')),
    ticket           text        NOT NULL,
    incident_sys_id  text        NOT NULL,
    sla_name         text        NOT NULL,
    percentage       numeric,
    planned_end      text,                     -- ServiceNow's planned_end_time, UTC
    priority         text,
    assignment_group text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_sla_sys_id, level)
);

ALTER TABLE suggestion DROP CONSTRAINT suggestion_kind_check;
ALTER TABLE suggestion ADD CONSTRAINT suggestion_kind_check
    CHECK (kind IN ('answer', 'kb_draft', 'kb_covered', 'remediation', 'diagnostic', 'problem', 'sla_alert'));
