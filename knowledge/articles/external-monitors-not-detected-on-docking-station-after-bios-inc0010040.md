---
id: KB-INC0010040-001
title: External monitors not detected on docking station after BIOS update
audience:
- service-desk
systems:
- hardware
symptoms:
- External monitors not detected on the docking station after a BIOS update
owner: service-desk
review_by: 2027-05-07
---

## Symptom
External monitors stay black when connected to USB‑C dock after a BIOS update; laptop screen works

## Cause
Dock firmware was older than the new BIOS supports, causing incompatibility

## Resolution
1. Update the dock firmware to the latest version using Dell Command Update or the vendor's firmware utility
2. Power‑cycle the dock: unplug the dock's power cable, wait about 30 seconds, then reconnect the power
3. Reconnect the dock to the laptop and attach the external monitors; they should now be detected

*Drafted by Jarvis from INC0010040. Check every step before merging.*
