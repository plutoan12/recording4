#!/bin/sh
set -eu
umask 077
while true; do
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    temp="/backups/db-$stamp.dump.partial"
    if pg_dump --format=custom --file="$temp" && pg_restore --list "$temp" >/dev/null; then
        mv "$temp" "/backups/db-$stamp.dump"
        date -u +%FT%TZ > /backups/last-success.txt
        echo "Database backup completed: $stamp"
    else
        echo 'Database backup failed' >&2
    fi
    # Existing media/backups are never deleted without a configured retention policy.
    sleep 86400
done
