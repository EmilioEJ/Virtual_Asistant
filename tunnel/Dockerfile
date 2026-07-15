# Túnel SSH (sidecar) hacia Ollama en el servidor GPU (LabITI).
# Reenvía 0.0.0.0:11434 (dentro de la red docker 'internal') -> Ollama del GPU.
# La llave privada se monta en /key (read-only) desde el host del VPS.
FROM alpine:3.20

RUN apk add --no-cache openssh-client autossh

# La key montada puede venir con owner del host; se copia a /tmp con perms 600
# (owner root) para que OpenSSH la acepte. Los args (-L ... user@host) llegan por
# 'command' del docker-compose.
RUN printf '#!/bin/sh\nset -e\ncp /key /tmp/id && chmod 600 /tmp/id\nexec autossh -M 0 -N \\\n  -o StrictHostKeyChecking=accept-new \\\n  -o UserKnownHostsFile=/dev/null \\\n  -o ServerAliveInterval=30 \\\n  -o ServerAliveCountMax=3 \\\n  -o ExitOnForwardFailure=yes \\\n  -i /tmp/id "$@"\n' > /entry.sh \
    && chmod +x /entry.sh

ENTRYPOINT ["/entry.sh"]
