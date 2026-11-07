---
id: KB-NET-001
title: GlobalProtect VPN error 809 or gateway unreachable
audience: [end-user, service-desk]
systems: [vpn]
symptoms: ["error 809", "VPN won't connect", "gateway unreachable", "VPN fails from hotel or home"]
owner: network-team
review_by: 2027-05-01
---

## Symptom
The GlobalProtect client shows *Error 809* or *Gateway not reachable*. Internet works without the VPN.

## Cause
The local network (home router, hotel, airport) blocks UDP ports 500/4500 used by IPsec, or the VPN profile is outdated.

## Resolution
1. Check that web pages open without the VPN.
2. In GlobalProtect: **Settings > Refresh portal**.
3. Switch to the SSL gateway `vpn-ssl.helios.local` (port 443), which works on almost every network.
4. Restart the `PanGPS` service (`services.msc`).
5. If it still fails, collect logs (**Settings > Troubleshooting > Collect logs**) and assign the ticket to **Network**.

If a whole office cannot connect, it is not a client problem: see runbook RB-NET-001.
