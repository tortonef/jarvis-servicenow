---
id: KB-M365-006
title: Can't join a Teams meeting organized by another company
audience: [end-user, service-desk]
systems: [teams, microsoft-365]
symptoms: ["can't join external Teams meeting", "your organization doesn't allow you to join", "supplier meeting link doesn't work", "stuck in the lobby of a customer meeting"]
owner: workplace-team
review_by: 2027-05-01
---

## Symptom
Joining a Teams meeting from a customer or supplier fails with *Your organization doesn't allow you to join this meeting*, or the user waits in the lobby forever.

## Cause
Helios allows external meetings only with domains on the external access list. New partners are not on it until someone requests them.

## Resolution
1. Ask the organizer to admit the user from the lobby: lobby waits are on their side.
2. As a workaround, join from the browser at `https://teams.microsoft.com` with **Join anonymously** (no Helios files are shared this way).
3. For a recurring partner, submit the catalog request **Teams external access** with the partner's domain; Workplace adds it to the allow list within one working day.
