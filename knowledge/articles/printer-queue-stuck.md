---
id: KB-PRN-001
title: Print jobs stuck in the queue
audience: [end-user, service-desk]
systems: [printing]
symptoms: ["nothing comes out of the printer", "documents stuck in queue", "Error - Printing", "printer not printing"]
owner: workplace-team
review_by: 2027-05-01
---

## Resolution on the PC
1. `services.msc` > stop **Print Spooler**.
2. Delete the files in `C:\Windows\System32\spool\PRINTERS`.
3. Start **Print Spooler** again and print a test page.

## If several users are affected
The queue is on the print server `PRT01`: assign to **Hardware**. The maintenance team follows runbook RB-PRN-001.
