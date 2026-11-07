#!/bin/sh
# Jarvis's SSH key for the lab servers is created inside the MID container, never on the host. The public half goes
# to the shared lab-keys volume, where app01/app02 bind it to the jarvis-agent forced command.
set -eu
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [ ! -f /keys/id_ed25519 ]; then
    ssh-keygen -q -t ed25519 -N '' -C jarvis@helios-mid -f /keys/id_ed25519
fi
cp /keys/id_ed25519 "$HOME/.ssh/id_ed25519" && chmod 600 "$HOME/.ssh/id_ed25519"
