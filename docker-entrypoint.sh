#!/bin/sh
# Make sure the data directory is writable by the unprivileged "app" user
# (older images ran as root, so existing volumes may be root-owned), then
# drop privileges. If the container is started with --user, just run.
set -e

DATA_DIR="$(dirname "${DATABASE_PATH:-/data/golinks.db}")"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown app:app "$DATA_DIR"
    find "$DATA_DIR" -maxdepth 1 \( -name '*.db*' -o -name 'secret_key' \) -exec chown app:app {} +
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
