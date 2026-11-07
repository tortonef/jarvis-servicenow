---
id: KB-IAM-003
title: Microsoft Authenticator on a new or lost phone
audience: [end-user, service-desk]
systems: [entra-id, mfa]
symptoms: ["new phone", "not receiving MFA notifications", "can't approve sign-in", "lost phone"]
owner: identity-team
review_by: 2027-05-01
---

## Symptom
The user changed or lost the phone and can no longer approve sign-ins to Microsoft 365.

## Resolution
1. Verify identity (employee ID and manager).
2. In **Entra ID > Users > Authentication methods**, choose **Require re-register MFA**.
3. Issue a **Temporary Access Pass** valid for 8 hours.
4. The user signs in with it and registers the new phone at `https://aka.ms/mysecurityinfo`.

If the phone was lost, also ask the user to sign out all sessions from the same page.
