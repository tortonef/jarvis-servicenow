---
id: KB-M365-003
title: OneDrive sync stuck or red cross on files
audience: [end-user, service-desk]
systems: [onedrive, microsoft-365]
symptoms: ["OneDrive not syncing", "red cross icon", "sync pending forever", "files not uploading"]
owner: workplace-team
review_by: 2027-05-01
---

## Resolution
1. Click the OneDrive icon and read the error: it usually names the file.
2. Rename files with invalid characters (`" * : < > ? / \ |`) and shorten paths longer than 400 characters.
3. Pause and resume syncing.
4. Reset the client: `%localappdata%\Microsoft\OneDrive\onedrive.exe /reset`, then start OneDrive again.
5. Check the storage quota in the OneDrive web page.
