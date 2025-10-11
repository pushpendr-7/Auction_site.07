"""
ASGI config for auction_site project with Django Channels.
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'auction_site.settings')

django_asgi_app = get_asgi_application()

try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack
    import auctions.routing

    application = ProtocolTypeRouter({
        'http': django_asgi_app,
        'websocket': AuthMiddlewareStack(
            URLRouter(auctions.routing.websocket_urlpatterns)
        ),
    })
except Exception:
    # Fallback to plain ASGI app if Channels is not available
    application = django_asgi_app
