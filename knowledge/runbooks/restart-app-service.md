---
id: RB-SRV-002
title: Restart the helios-portal application service
audience: [maintenance]
systems: [linux, helios-portal]
symptoms: ["portal not responding", "HTTP 502 from the portal", "helios-portal down", "intranet portal error"]
owner: platform-team
review_by: 2027-05-01
---

## When to use
The Helios portal on `APP01` or `APP02` returns errors or does not answer. Restarting one node at a time keeps the portal online behind the load balancer. Risk: medium, needs a Change during office hours.

## Pre-checks
1. `systemctl status helios-portal`: note the state and the last log lines.
2. `curl -fsS http://localhost:8080/health` on the node.
3. Make sure the other node is healthy before touching this one.

## Steps
1. `systemctl restart helios-portal`.
2. Wait 30 seconds, then `curl -fsS http://localhost:8080/health` must return `ok`.

## Rollback
If the service does not come back, `journalctl -u helios-portal -n 200` and attach the output to the incident; leave the other node serving and escalate to **Software**.
