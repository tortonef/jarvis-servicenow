# Helios Group IT knowledge base

Documentation as code for **Helios Group**, a fictional company used by the Jarvis demo: about 1,200 employees in Milan, Turin and Rome, Active Directory domain `helios.local`, Microsoft 365, SAP, and Linux application servers.

Every document here is the single source of truth. On merge to `main`, Jarvis ingests it into PostgreSQL (chunks + embeddings) and publishes it to the ServiceNow knowledge base **Helios Group IT**. Nobody edits those articles in ServiceNow.

## Layout

| Folder | For | Id prefix |
|---|---|---|
| `articles/` | End users and the Service Desk: troubleshooting and how-to | `KB-` |
| `runbooks/` | The maintenance team: operational procedures | `RB-` |

## Front matter

```yaml
---
id: KB-NET-001                 # unique, never reused; the ServiceNow article is matched on it
title: GlobalProtect VPN error 809 or gateway unreachable
audience: [end-user, service-desk]   # or [maintenance]
systems: [vpn]
symptoms: ["error 809", "VPN won't connect"]   # how users describe it: used for search
owner: network-team
review_by: 2027-05-01          # stale after this date
---
```

`python -m jarvis.knowledge check` validates every document; CI runs it on every pull request.

## Main systems

| System | Host |
|---|---|
| Domain controllers | `DC01`, `DC02` (`helios.local`) |
| File server | `FS01` (`\\fs01.helios.local\`) |
| Print server | `PRT01` |
| VPN | `vpn.helios.local`, SSL fallback `vpn-ssl.helios.local` (port 443) |
| SAP production | `sapprd.helios.local`, port 3200 |
| Application servers (Linux) | `APP01`, `APP02`, service `helios-portal` |
| Self-service password reset | `https://passwordreset.helios.local` |
