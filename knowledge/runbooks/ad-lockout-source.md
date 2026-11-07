---
id: RB-AD-002
title: Find the source of repeated account lockouts
audience: [maintenance]
systems: [active-directory]
symptoms: ["account keeps locking", "locked again after unlock", "event 4740"]
owner: identity-team
review_by: 2027-05-01
---

## Steps
1. Find the DC holding the PDC emulator role: `Get-ADDomain | Select PDCEmulator` (normally `DC01`).
2. On that DC, read event 4740 for the user:
   `Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4740} | Where-Object { $_.Properties[0].Value -eq '<sam>' } | Select -First 5`
3. The *Caller Computer Name* field names the device sending the bad password.
4. Typical sources: a phone mail app, a mapped drive with stored credentials, a scheduled task, an old session on a terminal server.
5. Ask the user to update or remove the credential on that device, then unlock with RB-AD-001.

## Escalate
If the caller is a server, assign to **Network** with the event details: it may be a misconfigured service.
