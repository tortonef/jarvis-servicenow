#!/bin/sh
# Lock a lab user the way it happens in real life: 6 bad passwords against dc01. Usage: lab/lock-user.sh alex.rivera
set -eu
user="${1:?usage: lab/lock-user.sh <account>}"
docker compose exec -T dc01 sh -c "for i in 1 2 3 4 5 6; do smbclient -L 127.0.0.1 -U \"HELIOS\\$user%not-the-password-\$i\" >/dev/null 2>&1; done
samba-tool user show '$user' --attributes=lockoutTime,badPwdCount | grep -E '^(lockoutTime|badPwdCount)'"
