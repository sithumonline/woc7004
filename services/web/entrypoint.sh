#!/bin/sh

HTTP_CTRL=$(printf '%s' "${CODECARBON_HTTP_CONTROL:-1}" | tr '[:upper:]' '[:lower:]')
WORKERS=${WEB_CONCURRENCY:-4}
THREADS=${WEB_THREADS:-2}

case "$HTTP_CTRL" in
  0|off|false|no)
    :
    ;;
  *)
    WORKERS=1
    CODECARBON_HTTP_CONTROL=1
    ;;
esac

export CODECARBON_HTTP_CONTROL

if [ $# -gt 0 ]; then
  exec "$@"
else
  exec gunicorn --bind 0.0.0.0:"${PORT:-8080}" project.wsgi:app --workers "$WORKERS" --threads "$THREADS"
fi
