---
id: RB-NET-001
title: VPN down for a whole office or many remote users
audience: [maintenance]
systems: [vpn, network]
symptoms: ["VPN down for everyone", "whole office can't connect", "many users error 809 at the same time"]
owner: network-team
review_by: 2027-05-01
---

## When to use
Many users fail at the same time (a P1). Single-user problems use KB-NET-001.

## Steps
1. Check the gateway: `Test-NetConnection vpn.helios.local -Port 443` from outside the network.
2. Check the gateway dashboard: active sessions, licence usage, CPU.
3. If sessions are at the licence limit, ask users to switch to `vpn-ssl.helios.local` while you free stale sessions.
4. If the gateway does not answer, fail over to the secondary gateway and inform the ISP.
5. Post updates on the P1 channel every 30 minutes.

## After
Open a Problem record with the timeline.
