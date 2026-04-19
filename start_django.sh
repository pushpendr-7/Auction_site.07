#!/bin/bash
export DJANGO_DEBUG=true
export PYTHONPATH=/home/runner/workspace
export PATH=/home/runner/workspace/.pythonlibs/bin:$PATH

cd /home/runner/workspace

# Run migrations first
python3.11 manage.py migrate --noinput 2>&1

# Collect static files
python3.11 manage.py collectstatic --noinput 2>&1

# Start daphne ASGI server
daphne -b 0.0.0.0 -p 8000 auction_site.asgi:application
