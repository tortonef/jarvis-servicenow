---
id: KB-EP-003
title: Slow laptop at startup or 100% CPU
audience: [end-user, service-desk]
systems: [windows]
symptoms: ["laptop very slow", "takes ages to boot", "fan always loud", "CPU at 100%"]
owner: workplace-team
review_by: 2027-05-01
---

## Resolution
1. **Task Manager > Startup apps**: disable what the user does not need.
2. Check whether Windows Update or an antivirus scan is running; let it finish.
3. Run `sfc /scannow`, then `DISM /Online /Cleanup-Image /RestoreHealth`.
4. Run the vendor diagnostics from the boot menu to check disk and fan.
5. If the laptop is older than 4 years, open a replacement request.
