#!/bin/sh
# Provisions helios.local once (state lives in volumes), then runs the DC in the foreground.
set -eu
: "${LAB_ADMIN_PASSWORD:?}" "${LAB_USER_PASSWORD:?}" "${LAB_SERVICE_PASSWORD:?}"

if [ ! -f /var/lib/samba/private/sam.ldb ]; then
    rm -f /etc/samba/smb.conf
    samba-tool domain provision --realm=HELIOS.LOCAL --domain=HELIOS --server-role=dc \
        --dns-backend=SAMBA_INTERNAL --host-name=dc01 --adminpass="$LAB_ADMIN_PASSWORD" --use-rfc2307
    # Lock after 5 bad passwords for 30 minutes, like the Helios policy in KB-IAM-001
    samba-tool domain passwordsettings set --account-lockout-threshold=5 \
        --account-lockout-duration=30 --reset-account-lockout-after=30
    samba-tool ou create "OU=Staff,DC=helios,DC=local"
    samba-tool ou create "OU=Service Accounts,DC=helios,DC=local"
    for u in "alex.rivera Alex Rivera" "maria.rossi Maria Rossi" "luca.bianchi Luca Bianchi" "giulia.verdi Giulia Verdi"; do
        set -- $u
        samba-tool user create "$1" "$LAB_USER_PASSWORD" --userou="OU=Staff" --given-name="$2" --surname="$3"
    done
    # Jarvis's own account: no admin rights; Phase 3 delegates only the unlock right on OU=Staff
    samba-tool user create svc_jarvis "$LAB_SERVICE_PASSWORD" --userou="OU=Service Accounts" \
        --description="Jarvis automation (least privilege)"
    samba-tool user setexpiry svc_jarvis --noexpiry
fi
exec samba --foreground --no-process-group
