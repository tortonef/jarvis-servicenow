---
id: RB-PRN-001
title: Restart the spooler on print server PRT01
audience: [maintenance]
systems: [printing, windows-server]
symptoms: ["nobody can print", "printer queue stuck for everyone", "print server not responding"]
owner: workplace-team
review_by: 2027-05-01
---

## When to use
Several users cannot print and their local spoolers are fine (KB-PRN-001). Risk: low, printing stops for about one minute.

## Steps
1. On `PRT01`: `Get-Printer | Get-PrintJob | Where JobStatus -match 'Error'` to see stuck jobs.
2. `Stop-Service Spooler`.
3. Delete the files in `C:\Windows\System32\spool\PRINTERS`.
4. `Start-Service Spooler`.

## Verify
Print a test page on one of the affected printers.
