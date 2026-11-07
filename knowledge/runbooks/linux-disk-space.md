---
id: RB-SRV-001
title: Free disk space on a Linux application server
audience: [maintenance]
systems: [linux, helios-portal]
symptoms: ["disk usage above 90%", "no space left on device", "/var full", "application can't write logs"]
owner: platform-team
review_by: 2027-05-01
---

## When to use
Monitoring alerts on disk usage of `APP01` or `APP02`, or the application fails with *No space left on device*. Risk: low.

## Pre-checks
1. `df -h /` and `df -h /var`: note the usage.
2. `du -xh /var --max-depth=2 | sort -h | tail -15`: find what grew.

## Steps
1. Trim the systemd journal: `journalctl --vacuum-time=7d`.
2. Remove rotated application logs older than 14 days:
   `find /var/log/helios-portal -name '*.log.*' -mtime +14 -delete`.
3. Clean the package cache: `apt-get clean`.

## Verify
`df -h /var` is below 80%.

## Escalate
If usage is still above 80%, open a Change to extend the volume and assign it to **Software**.
