---
id: KB-M365-004
title: Excel closes when opening large workbooks
audience: [end-user, service-desk]
systems: [excel, microsoft-365]
symptoms: ["Excel crashes", "spreadsheet closes on open", "big workbook shuts down Excel", "Excel not responding"]
owner: workplace-team
review_by: 2027-05-01
---

## Resolution
1. Start `excel.exe /safe` to rule out add-ins.
2. Disable hardware graphics acceleration: **File > Options > Advanced > Display**.
3. Check that 64-bit Office is installed (**File > Account > About Excel**): files over 2 GB need it.
4. Run **Quick Repair** from **Settings > Apps > Microsoft 365 > Modify**.

For workbooks over 1 GB, suggest Power BI or splitting the data: they hit the memory limits of a standard laptop.
