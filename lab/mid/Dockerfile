# ServiceNow's MID Server image (built from the official recipe in lab/mid/recipe) + the tools Jarvis's MID Script
# Includes call: LDAP client for JarvisLdap, SSH client for JarvisSsh
ARG MID_IMAGE=mid:brazil-patch2
FROM ${MID_IMAGE}
USER root
RUN dnf install -y openldap-clients openssh-clients && dnf clean all && rm -rf /tmp/* \
 && mkdir /keys && chown mid /keys
COPY keys.sh /opt/jarvis/keys.sh
RUN chmod 755 /opt/jarvis/keys.sh
USER mid
ENTRYPOINT ["/bin/sh", "-c", "/opt/jarvis/keys.sh && exec /opt/snc_mid_server/init start"]
