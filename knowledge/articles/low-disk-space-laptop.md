---
id: KB-EP-002
title: Low disk space on a laptop
audience: [end-user, service-desk]
systems: [windows]
symptoms: ["disk full", "no space left", "can't save files", "C drive red"]
owner: workplace-team
review_by: 2027-05-01
---

## Resolution
1. Run **Disk Cleanup** (`cleanmgr`) and choose **Clean up system files**.
2. Empty `%TEMP%` and the Downloads folder.
3. Set OneDrive to **Files On-Demand**, then **Free up space** on large folders.
4. Look for large items with **Settings > System > Storage**; a common one is an Outlook `.ost` file over 20 GB: reduce **Mail to keep offline** to 6 months.
5. If the disk is under 256 GB and the user works with large data, open a hardware upgrade request.
