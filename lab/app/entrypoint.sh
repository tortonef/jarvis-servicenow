#!/bin/sh
# Helios application server (APP01/APP02): sshd for Jarvis's restricted key, the fake helios-portal on :8080,
# and a small log volume that starts almost full (RB-SRV-001 scenario).
set -eu
LOGS=/var/log/helios-portal

# Jarvis's public key comes from the MID Server through the shared lab-keys volume
until [ -f /keys/id_ed25519.pub ]; do echo "waiting for the MID Server key..."; sleep 3; done
printf 'command="/usr/local/bin/jarvis-agent",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty %s\n' \
    "$(cat /keys/id_ed25519.pub)" > /home/jarvis/.ssh/authorized_keys
chown -R jarvis:jarvis /home/jarvis/.ssh && chmod 600 /home/jarvis/.ssh/authorized_keys

# Fill the 64 MB log volume to about 90%: 40 rotated logs older than 14 days, plus today's log
if [ -z "$(ls -A "$LOGS")" ]; then
    for i in $(seq 1 40); do
        head -c 1400000 /dev/zero | tr '\0' 'x' > "$LOGS/portal.log.$i"
        touch -d "$((15 + i)) days ago" "$LOGS/portal.log.$i"
    done
    echo "$(date -u) helios-portal started" > "$LOGS/portal.log"
    chown -R jarvis:jarvis "$LOGS"
fi

mkdir -p /srv/portal && echo ok > /srv/portal/health
su jarvis -s /bin/sh -c "python3 -m http.server 8080 --directory /srv/portal >/dev/null 2>&1 &"
exec /usr/sbin/sshd -D -e
