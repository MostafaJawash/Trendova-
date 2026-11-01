"""
Authentication and authorization dependencies.
"""
from typing import List
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.users.models import User, UserRole

# HTTP Bearer security scheme
security = HTTPBearer(auto_error=False)


class AuthenticationError(HTTPException):
    """Custom authentication error."""
    def __init__(self, detail: str = "Could not validate credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class AuthorizationError(HTTPException):
    """Custom authorization error."""
    def __init__(self, detail: str = "Not enough permissions"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.

    Args:
        credentials: HTTP Bearer credentials extracted from Authorization header
        db: Database session

    Returns:
        Current authenticated User instance

    Raises:
        AuthenticationError: If token is invalid, expired, or user not found
    """
    if credentials is None:
        raise AuthenticationError("Missing authentication credentials")

    try:
        payload = decode_access_token(credentials.credentials)
        subject: str = payload.get("sub")
        if subject is None:
            raise AuthenticationError("Invalid token: missing subject claim")
    except InvalidTokenError:
        raise AuthenticationError("Invalid authentication credentials")

    # Convert subject to user ID (BIGINT UNSIGNED in database)
    try:
        user_id = int(subject)
    except (ValueError, TypeError):
        raise AuthenticationError("Invalid token: invalid subject format")

    # Load user from database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AuthenticationError("User not found")

    return user


async def require_role(allowed_roles: List[UserRole]) -> User:
    """
    Dependency factory to require specific user roles.

    Args:
        allowed_roles: List of allowed UserRole values

    Returns:
        Dependency function that returns the user if authorized

    Raises:
        AuthorizationError: If user lacks required role
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise AuthorizationError("User does not have required permissions")
        return current_user

    return role_checker


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency to require admin role.

    Args:
        current_user: Current authenticated user

    Returns:
        Current user if they are an admin

    Raises:
        AuthorizationError: If user is not an admin
    """
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Admin access required")
    return current_user
