---
id: KB-EP-001
title: BitLocker asks for the recovery key at startup
audience: [end-user, service-desk]
systems: [bitlocker, intune]
symptoms: ["48-digit code at startup", "blue screen asks for recovery key", "can't get to Windows", "BitLocker recovery"]
owner: workplace-team
review_by: 2027-05-01
---

## Symptom
Before Windows starts, a blue screen asks for a 48-digit BitLocker recovery key and shows a *Key ID*.

## Cause
Usually a BIOS update, a dock connected at boot, or a TPM change.

## Resolution
1. Verify the user's identity (employee ID and manager) before giving out any key.
2. In **Intune > Devices > [hostname] > Recovery keys**, find the key matching the Key ID.
3. Read the key to the user by phone.
4. Once Windows starts, ask the user to reboot once more: it should not ask again. If it does, assign to **Hardware** to check the TPM.
