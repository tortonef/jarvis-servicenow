---
id: KB-IAM-002
title: Reset a forgotten or expired password
audience: [end-user, service-desk]
systems: [active-directory]
symptoms: ["forgot password", "password expired", "need a new password"]
owner: identity-team
review_by: 2027-05-01
---

## Self-service
Users reset their password at `https://passwordreset.helios.local` with MFA. The new password must have 12 or more characters and cannot reuse the last 10.

## Service Desk
If the user has no MFA registered:
1. Verify identity: employee ID and the manager's name, checked in ServiceNow.
2. Reset the password in ADUC with **User must change password at next logon**.
3. Give the temporary password by phone only, never by email or chat.
4. Ask the user to register MFA (KB-IAM-003).
