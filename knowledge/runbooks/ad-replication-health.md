---
id: RB-AD-003
title: Check Active Directory replication and DNS health
audience: [maintenance]
systems: [active-directory, dns]
symptoms: ["changes not replicating", "password change not applied everywhere", "DNS failures across the office"]
owner: identity-team
review_by: 2027-05-01
---

## Steps (read only)
1. `repadmin /replsummary`: every DC must show 0 failures.
2. `repadmin /showrepl DC02`: check the last success time for each partition.
3. `dcdiag /s:DC01 /test:dns /v`: all DNS tests must pass.
4. `nslookup helios.local DC01` and `nslookup helios.local DC02` must both answer.

## If something fails
- Replication errors with *RPC server unavailable*: check that the two DCs reach each other on TCP 135 and 49152-65535.
- DNS test failures on one DC: restart the **DNS Server** service on that DC only, outside office hours, through a Change.
- Anything else: open a Problem record and assign to **Network**.
