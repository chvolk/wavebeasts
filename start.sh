#!/usr/bin/env sh
set -e
# stateless resolver (engine) on localhost; the site calls it for generation/render
WAVEBEAST_ADDR=:8777 WAVEBEAST_DB="${WAVEBEAST_DB:-/tmp/wavebeast.db}" wavebeast &
python manage.py migrate --noinput
python manage.py run_matchmaker --loop --interval "${MATCHMAKER_INTERVAL:-180}" &
exec gunicorn wavebeasts.wsgi --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 60
