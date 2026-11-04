import jwt
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
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
