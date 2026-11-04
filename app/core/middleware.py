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
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response
