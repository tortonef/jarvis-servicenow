---
id: RB-SRV-005
title: Nightly backup job failed
audience: [maintenance]
systems: [backup]
symptoms: ["backup failed", "backup job error", "missed backup"]
owner: platform-team
review_by: 2027-05-01
---

## Steps
1. Open the backup console and read the error of the failed job.
2. Common causes and fixes:
   - **Repository full**: delete restore points beyond the retention policy, then rerun.
   - **Guest credentials rejected**: the service account password changed; update it in the console.
   - **Snapshot timeout**: the VM was busy; rerun the job outside peak hours.
3. Rerun the failed job and wait for *Success*.

## Escalate
Two consecutive failures on the same server: open a Problem record and inform the server owner.
