import jwt
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db, route_read
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.core.tokens import is_revoked
from app.modules.users import service as users

bearer = HTTPBearer(auto_error=False)

def current(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    if credentials is None:
        raise AppError(401, 'UNAUTHORIZED', 'Missing authentication credentials', headers={'WWW-Authenticate': 'Bearer'})
    try:
        data = decode_access_token(credentials.credentials)
        user_id = int(data['sub'])
        if is_revoked(db, data['jti']):
            raise ValueError('revoked')
        user = users.get_by_id(db, user_id)
        if user is None or not user.is_active:
            raise ValueError('inactive')
        return user, data
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise AppError(401, 'UNAUTHORIZED', 'Invalid authentication credentials', headers={'WWW-Authenticate': 'Bearer'})

def admin(auth=Depends(current)):
    user, _ = auth
    if user.role != 'admin':
        raise AppError(403, 'FORBIDDEN', 'Admin access required')
    return user

def read_db(auth=Depends(current), primary: Session = Depends(get_db)):
    """Session for reads that may be slightly stale (my orders, admin lists, dashboard stats): the read replica,
    or the PRIMARY when the replica is off/down, Redis is unreachable, or this user wrote in the last RYW window.
    On the primary it REUSES the request's own session (`get_db` is resolved once per request, `current` uses it too)."""
    db, owned = route_read(auth[0].id, primary=primary)
    try:
        yield db
    finally:
        if owned:
            db.close()
