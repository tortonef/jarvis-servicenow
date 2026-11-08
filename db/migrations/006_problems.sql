-- Phase 4: Problems proposed from clusters of similar incidents are audited too.
ALTER TABLE suggestion DROP CONSTRAINT suggestion_kind_check;
ALTER TABLE suggestion ADD CONSTRAINT suggestion_kind_check
    CHECK (kind IN ('answer', 'kb_draft', 'kb_covered', 'remediation', 'diagnostic', 'problem'));
