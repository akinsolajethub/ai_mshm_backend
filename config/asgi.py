"""
AI-MSHM – ASGI Configuration
Handles both HTTP (Django) and WebSocket (Channels) connections.
"""
import os
from dotenv import load_dotenv
load_dotenv()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

django_asgi_app = get_asgi_application()

# Import after Django setup
from apps.notifications.routing import websocket_urlpatterns  # noqa
from core.middleware import JWTAuthMiddlewareStack           # noqa

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)