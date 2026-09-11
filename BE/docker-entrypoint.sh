#!/bin/sh
# Applies pending Alembic migrations before the app starts — this is the
# real schema-migration step for a deployed environment (app/core/db.py's
# create_all() is only a harmless local-dev safety net, not a substitute for
# this). Fails the container start (rather than booting against a stale
# schema) if migrations don't apply cleanly.
set -e

echo "Running database migrations..."
(cd /app/BE && alembic upgrade head)

echo "Starting application..."
exec "$@"
