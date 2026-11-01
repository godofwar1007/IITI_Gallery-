"""Portable single-origin ASGI gateway; organizer APIs retain their authentication."""
from contextlib import asynccontextmanager
import os
import re
from urllib.parse import urlparse
from fastapi import FastAPI
from .api import make_apps

PUBLIC = {'/e/workshop', '/api/v1/event', '/api/v1/join', '/api/v1/upload-intents',
          '/api/v1/me/submissions', '/api/v1/receipt/recover', '/health/live', '/health/ready'}
PUBLIC_PATTERN = re.compile(r'^/api/v1/(?:uploads/[^/]+/content|me/submissions/[^/]+)$')


class Gateway:
    def __init__(self, service):
        if service.config.local_demo:
            raise ValueError('The public gateway refuses password-free local demo mode')
        if not service.config.admin_hash:
            raise ValueError('Organizer authentication is required')
        self.service = service
        self.public, self.admin = make_apps(service)
        self.explicit_origin = bool(os.environ.get('GALLERY_PUBLIC_URL'))

        @asynccontextmanager
        async def lifespan(app):
            try:
                await service.start()
                yield
            finally:
                await service.stop()
        self.lifecycle = FastAPI(lifespan=lifespan)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.lifecycle(scope, receive, send)
        # With no Vercel URL yet, use this Modal endpoint for QR links. Host validation
        # still happens in both apps; no arbitrary Origin header becomes trusted.
        if not self.explicit_origin:
            host = dict(scope.get('headers', [])).get(b'host', b'').decode('ascii', errors='ignore')
            if host.endswith('.modal.run'):
                self.service.config.public_url = 'https://' + host
        path = scope.get('path', '')
        app = self.public if path in PUBLIC or PUBLIC_PATTERN.fullmatch(path) else self.admin
        await app(scope, receive, send)
