#!/bin/bash
export PYTHONPATH=/home/runner/workspace
export PATH=/home/runner/workspace/.pythonlibs/bin:$PATH
export DJANGO_SETTINGS_MODULE=auction_site.settings

# Set DEBUG=true only in development (not in production deployment)
if [ -z "$REPLIT_DEPLOYMENT" ]; then
    export DJANGO_DEBUG=true
fi

cd /home/runner/workspace

# Run migrations
python3.11 manage.py migrate --noinput 2>&1

# Collect static files
python3.11 manage.py collectstatic --noinput 2>&1

# Start daphne ASGI server on $PORT or default 8000
PORT="${PORT:-8000}"
daphne -b 0.0.0.0 -p "$PORT" auction_site.asgi:application
