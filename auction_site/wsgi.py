"""
WSGI config for auction_site project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'auction_site.settings')

application = get_wsgi_application()

# Attempt to run pending migrations automatically on startup.
# This helps ensure new tables (e.g., `auctions_userprofile`) exist in
# environments where deploy pipelines don't run `manage.py migrate`.
try:
    from django.core.management import call_command
    # Idempotent: safe to call on every worker start
    call_command('migrate', interactive=False, run_syncdb=True, verbosity=0)
except Exception:
    # If migrations fail here (e.g., read-only context), continue serving.
    # Admin can run migrations manually via CLI.
    pass
