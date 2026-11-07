---
id: RB-SRV-004
title: Renew an expiring TLS certificate
audience: [maintenance]
systems: [pki, helios-portal]
symptoms: ["certificate expires soon", "browser shows certificate error", "TLS handshake failure"]
owner: platform-team
review_by: 2027-05-01
---

## Check
`echo | openssl s_client -connect portal.helios.local:443 2>/dev/null | openssl x509 -noout -enddate`

Renew when fewer than 30 days remain.

## Steps (needs a Change)
1. Create a CSR on the server: `openssl req -new -newkey rsa:3072 -nodes -keyout portal.key -out portal.csr -subj "/CN=portal.helios.local"`.
2. Submit the CSR to the internal CA through the catalog item **Certificate request**.
3. Install the issued certificate in `/etc/helios-portal/tls/`, keeping the old one as `.bak`.
4. Restart the service one node at a time with RB-SRV-002.

## Rollback
Restore the `.bak` files and restart the service.
