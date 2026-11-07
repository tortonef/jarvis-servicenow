---
id: KB-NET-003
title: Internal websites don't open but the Internet works
audience: [end-user, service-desk]
systems: [dns, vpn]
symptoms: ["intranet not loading", "server not found for helios.local", "internal site can't be reached", "DNS error"]
owner: network-team
review_by: 2027-05-01
---

## Symptom
Public websites work, but internal ones (`*.helios.local`, the intranet, SAP web) fail with *server not found*.

## Cause
The device is not using Helios DNS servers: VPN not connected, split DNS not applied, or a stale DNS cache.

## Resolution
1. If remote, connect the VPN first (KB-NET-001).
2. Run `ipconfig /flushdns`.
3. Run `nslookup intranet.helios.local`: the answering server must be `DC01` or `DC02`.
4. If another server answers, disconnect and reconnect the VPN, then reboot.
5. If `nslookup` fails from the office network too, assign to **Network**: possible DNS outage (see runbook RB-AD-003).
