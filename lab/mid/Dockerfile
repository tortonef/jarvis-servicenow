# ServiceNow's MID Server image (built from the official recipe in lab/mid/recipe) + LDAP client tools for JarvisLdap
ARG MID_IMAGE=mid:brazil-patch2
FROM ${MID_IMAGE}
USER root
RUN dnf install -y openldap-clients && dnf clean all && rm -rf /tmp/*
USER mid
