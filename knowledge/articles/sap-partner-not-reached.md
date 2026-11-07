---
id: KB-APP-001
title: SAP GUI error Partner not reached
audience: [end-user, service-desk]
systems: [sap]
symptoms: ["partner not reached", "SAP won't connect", "SAP logon error"]
owner: sap-basis
review_by: 2027-05-01
---

## Cause
VPN not connected (from remote), or an outdated system entry in SAP Logon.

## Resolution
1. If remote, connect the VPN (KB-NET-001).
2. Refresh `SAPUILandscape.xml` from `\\fs01.helios.local\sap\config`.
3. Test the port: `Test-NetConnection sapprd.helios.local -Port 3200`.
4. If the port does not answer from the office, open an incident for **SAP Basis**: possible system outage.
