---
id: KB-IAM-001
title: Account locked out after a password change
audience: [end-user, service-desk]
systems: [active-directory]
symptoms: ["account locked", "too many sign-in attempts", "can't log in after password change", "locked out several times a day"]
owner: identity-team
review_by: 2027-05-01
---

## Symptom
Windows says the account is locked. It happens again a few minutes or hours after unlocking.

## Cause
A device or app still tries the old password: phone mail app, mapped drives, saved Wi-Fi credentials, Windows Credential Manager.

## Resolution
1. Unlock the account: the Service Desk follows runbook **RB-AD-001** (or the user uses the self-service portal).
2. Ask the user to update the password on the phone (Outlook or Mail app) and on `CORP-WIFI`.
3. Clear old entries in **Windows Credential Manager**.
4. If the lockout comes back, find the source with runbook **RB-AD-002**.
