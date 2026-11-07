---
id: KB-NET-002
title: Corporate Wi-Fi CORP-WIFI connected but no Internet
audience: [end-user, service-desk]
systems: [wifi, nac]
symptoms: ["Wi-Fi connected but no internet", "pages don't load on wireless", "works with cable not Wi-Fi"]
owner: network-team
review_by: 2027-05-01
---

## Symptom
The laptop shows *Connected* to `CORP-WIFI` but no website loads. A network cable works.

## Cause
Expired machine certificate, or the device is missing from the NAC group, so it lands in the quarantine VLAN.

## Resolution
1. Run `gpupdate /force` and reboot.
2. Open `certlm.msc > Personal > Certificates` and check the machine certificate is valid.
3. Forget `CORP-WIFI` and reconnect.
4. If the certificate is missing or expired, assign to **Network** with hostname and MAC address.

If several people on the same floor lose Wi-Fi at the same time, assign to **Network** as an access point issue.
