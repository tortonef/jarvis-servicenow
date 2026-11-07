---
id: KB-M365-005
title: Shared mailbox missing in Outlook
audience: [end-user, service-desk]
systems: [outlook, exchange-online]
symptoms: ["shared mailbox not showing", "can't see team mailbox", "send as permission"]
owner: workplace-team
review_by: 2027-05-01
---

## How it works
Shared mailboxes appear automatically in Outlook about one hour after the user gets **Full Access**. Access is requested through the catalog item **Shared mailbox access** and approved by the mailbox owner.

## Resolution
1. Check the request was approved and at least one hour has passed.
2. Restart Outlook.
3. If it still does not appear, add it by hand: **File > Account Settings > Change > More Settings > Advanced > Add**.
4. For *Send As* errors, check the permission in the Exchange admin center and wait up to one hour.
