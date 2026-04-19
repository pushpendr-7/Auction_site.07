# Workspace

## Overview

Django auction site deployed on Replit. This is a full-featured auction platform with WebSocket support (Django Channels), SQLite database, and user authentication.

## Stack

- **Language**: Python 3.11
- **Framework**: Django 5.2 with Django Channels (WebSockets)
- **ASGI Server**: Daphne
- **Database**: SQLite (db.sqlite3)
- **Static Files**: WhiteNoise
- **Media**: Local file storage (Cloudinary optional via env vars)

## Project Structure

- `auction_site/` — Django project settings, urls, asgi config
- `auctions/` — Main Django app (models, views, forms, consumers)
- `templates/` — Django HTML templates
- `static/` — Static files (CSS, JS, images)
- `staticfiles/` — Collected static files (generated)
- `manage.py` — Django management script
- `start_django.sh` — Startup script

## Key Commands

- `python3.11 manage.py migrate` — Run database migrations
- `python3.11 manage.py collectstatic` — Collect static files
- `python3.11 manage.py createsuperuser` — Create admin user
- `bash start_django.sh` — Start the server (port 8000)

## Environment Variables (Optional)

- `SECRET_KEY` — Django secret key
- `DJANGO_DEBUG` — Set to "true" for debug mode
- `CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET` — Cloudinary media storage
- `REDIS_URL` — Redis for Django Channels (falls back to in-memory)
- `DATABASE_URL` — PostgreSQL database (falls back to SQLite)

## Monorepo Info

- **Monorepo tool**: pnpm workspaces (for existing Node.js artifacts)
- **Node.js version**: 24
- **Package manager**: pnpm
