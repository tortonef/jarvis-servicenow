---
id: RB-SRV-003
title: "Free space on the C: drive of a Windows server"
audience: [maintenance]
systems: [windows-server]
symptoms: ["C: drive full on server", "low disk space alert on FS01", "Windows update fails for disk space"]
owner: platform-team
review_by: 2027-05-01
---

## Steps
1. Check usage: `Get-PSDrive C`.
2. Clean the component store: `Dism.exe /Online /Cleanup-Image /StartComponentCleanup`.
3. Delete IIS and application logs older than 30 days:
   `Get-ChildItem C:\inetpub\logs -Recurse -File | Where LastWriteTime -lt (Get-Date).AddDays(-30) | Remove-Item`.
4. Empty `C:\Windows\Temp`.

## Verify
At least 15% free space on C:.

## Never
Delete files under `C:\Windows\WinSxS` by hand, or move the page file without a Change.
