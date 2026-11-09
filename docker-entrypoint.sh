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
    # Keep only NET_BIND_SERVICE so PORT=80 works on hosts that don't allow
    # unprivileged low ports (Docker's default capability set includes it).
    exec setpriv --reuid=app --regid=app --init-groups \
        --inh-caps=-all,+net_bind_service --ambient-caps=-all,+net_bind_service "$@"
fi

exec "$@"
