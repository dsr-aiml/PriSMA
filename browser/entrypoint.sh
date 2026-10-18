#!/bin/sh
set -eu
# The image's pwuser UID can vary. Create private writable directories as that
# user inside ephemeral mounts instead of assuming a numeric UID in Compose.
umask 077
mkdir -p /home/pwuser/.cache /home/pwuser/.pki
exec uvicorn service:app --host 0.0.0.0 --port 8010 --workers 1
