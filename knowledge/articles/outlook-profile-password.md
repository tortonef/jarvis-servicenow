---
id: KB-M365-001
title: Outlook stuck on Loading profile or asking for the password
audience: [end-user, service-desk]
systems: [outlook, microsoft-365]
symptoms: ["Outlook won't open", "stuck on loading profile", "Outlook keeps asking for password", "credentials prompt every few minutes"]
owner: workplace-team
review_by: 2027-05-01
---

## Symptom
Outlook hangs on *Loading profile*, or shows a password prompt again and again.

## Resolution
1. Close Outlook. In **Windows Credential Manager**, remove the `MicrosoftOffice16_Data` entries.
2. Start `outlook.exe /safe` to rule out a faulty add-in.
3. If safe mode works, disable add-ins in **File > Options > Add-ins** and restart normally.
4. Last resort: **Control Panel > Mail > Show Profiles**, add a new profile and set it as default.

If the prompt appeared right after a password change, also check KB-IAM-001.
