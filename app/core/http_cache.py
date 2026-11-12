"""Reusable HTTP-cache helper (ETag / If-None-Match). Used explicitly by the product endpoints, NOT a global middleware,
so personal or write responses can never get a validator by accident.

Strong ETag = hash of the exact response body bytes. Headers:
  Cache-Control: public, no-cache      (public endpoints)  |  private, no-cache  (authenticated endpoints)
  Vary: Accept-Encoding[, Authorization]
`no-cache` means "store it, but revalidate every time": the browser asks with If-None-Match and gets a 304 without a body.
"""
from fastapi import Request, Response
from app.core.config import settings


def matches(if_none_match, etag: str) -> bool:
    """If-None-Match comparison (weak comparison per RFC 9110): several values, `*` and the W/ form are honoured."""
    if if_none_match is None:
        return False
    header = if_none_match.strip()
    if header == '*':
        return True
    wanted = etag[2:] if etag.startswith('W/') else etag
    for part in header.split(','):
        part = part.strip()
        if part.startswith('W/'):
            part = part[2:]
        if part == wanted:
            return True
    return False


def respond(request: Request, body: bytes, etag, *, public=False, cache_status=None, status_code=200) -> Response:
    """200 with the body, or 304 with an empty body (ETag and Cache-Control are still sent)."""
    headers = {}
    if cache_status is not None:
        headers['X-Cache'] = cache_status
    if settings.etag_enabled and etag:
        headers['ETag'] = etag
        headers['Cache-Control'] = 'public, no-cache' if public else 'private, no-cache'
        headers['Vary'] = 'Accept-Encoding' if public else 'Accept-Encoding, Authorization'
        if matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
    return Response(content=body, status_code=status_code, media_type='application/json', headers=headers)
