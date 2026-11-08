#!/bin/sh
# Simulate a portal outage on one lab server (RB-SRV-002 scenario). Usage: lab/break-portal.sh app01
set -eu
host="${1:?usage: lab/break-portal.sh <app01|app02>}"
docker compose exec -T -u jarvis "$host" pkill -f 'http.server 8080' && echo "helios-portal stopped on $host"
