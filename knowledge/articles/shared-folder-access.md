---
id: KB-IAM-004
title: Access denied to a shared folder
audience: [end-user, service-desk]
systems: [file-server, active-directory]
symptoms: ["access denied", "can't open network drive", "need permission to shared folder", "new in the team"]
owner: identity-team
review_by: 2027-05-01
---

## How access works
Shares on `FS01` are granted through AD groups named `FS_<Department>_RW` (read and write) and `FS_<Department>_RO` (read only). Access is never given to single users.

## Resolution
1. The user submits the catalog request **Shared folder access**; the manager approves it.
2. After the group change, the user signs out and in again, or runs `klist purge`.
3. If access is still denied, check the group membership in ADUC and the share permissions on `FS01`, then assign to **Service Desk** with both screenshots.
