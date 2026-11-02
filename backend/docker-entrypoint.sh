#!/bin/sh
# Apply migrations, seed the synthetic fleet (idempotent), then start the API, MQTT broker and simulator.
set -e
alembic upgrade head
python -m app.db.seed
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
