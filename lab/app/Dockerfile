# Helios application server for the lab (APP01, APP02): Debian packages only
FROM debian:bookworm-slim
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server python3 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/sh jarvis \
 && mkdir -p /home/jarvis/.ssh /run/sshd /var/log/helios-portal \
 && sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
COPY jarvis-agent /usr/local/bin/jarvis-agent
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /usr/local/bin/jarvis-agent /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
