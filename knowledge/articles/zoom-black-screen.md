---
id: KB-EP-004
title: Zoom screen sharing shows a black screen
audience: [end-user, service-desk]
systems: [zoom]
symptoms: ["black screen when sharing", "participants can't see my screen", "presenting shows black"]
owner: workplace-team
review_by: 2027-05-01
---

## Symptom
When the user shares the screen in Zoom, the others see only black. Audio and video work.

## Cause
Zoom's GPU hardware acceleration for screen sharing conflicts with the Intel graphics driver on some laptops (seen on Dell Latitude 5440).

## Resolution
1. Open **Zoom > Settings > Share Screen > Advanced**.
2. Uncheck **Enable hardware acceleration for screen sharing**.
3. Restart Zoom and test sharing.

This article was first drafted by Jarvis from a resolved incident and then reviewed.
