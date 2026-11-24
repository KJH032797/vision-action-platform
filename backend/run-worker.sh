#!/bin/sh
set -eu
python manage.py camera_sessions &
camera=$!
celery -A config.celery:app worker --loglevel=INFO --concurrency=1 &
worker=$!
cleanup() {
    kill "$camera" "$worker" 2>/dev/null || true
    wait "$camera" "$worker" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM
while kill -0 "$camera" 2>/dev/null && kill -0 "$worker" 2>/dev/null; do
    sleep 1
done
exit 1
