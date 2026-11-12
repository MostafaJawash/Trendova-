from fastapi import Request
from fastapi.responses import JSONResponse
import logging

log=logging.getLogger(__name__)

STRICT_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
DOCS_CSP = "default-src 'self' https: 'unsafe-inline' data:; object-src 'none'"

async def security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        log.exception('Unhandled request error')
        response = JSONResponse({'error':{'code':'INTERNAL_ERROR','message':'An unexpected error occurred','details':[]}},status_code=500)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = DOCS_CSP if request.url.path in ('/docs', '/redoc') else STRICT_CSP
    if request.url.path.startswith('/api/') and 'cache-control' not in response.headers:
        response.headers['Cache-Control'] = 'no-store'   # endpoints that opt in to ETag validation set their own value
    return response


class MergeVary:
    """ASGI middleware (outermost): GZipMiddleware appends its own `Vary: Accept-Encoding`; merge all Vary headers into one
    without duplicate tokens (`Vary: Accept-Encoding, Authorization`)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def merged(message):
            if message['type'] == 'http.response.start':
                tokens, rest = [], []
                for k, v in message['headers']:
                    if k.lower() == b'vary':
                        for t in v.decode().split(','):
                            t = t.strip()
                            if t and t.lower() not in (x.lower() for x in tokens):
                                tokens.append(t)
                    else:
                        rest.append((k, v))
                if tokens:
                    rest.append((b'vary', ', '.join(tokens).encode()))
                message = {**message, 'headers': rest}
            await send(message)
        await self.app(scope, receive, merged)
