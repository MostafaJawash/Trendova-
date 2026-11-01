"""
Security utilities for authentication and authorization.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Union
from pwdlib import PasswordHash
import jwt
from jwt.exceptions import InvalidTokenError
from app.core.config import settings

# Password hashing using Argon2 via pwdlib
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using Argon2.

    Args:
        password: Plaintext password to hash

    Returns:
        Argon2-encoded password hash
    """
    return password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored hash.

    Args:
        plain_password: Plaintext password to verify
        hashed_password: Stored password hash to compare against

    Returns:
        True if password matches, False otherwise
    """
    try:
        return password_hasher.verify(plain_password, hashed_password)
    except Exception:
        # Return False for any verification error (malformed hash, etc.)
        return False


def create_access_token(subject: Union[str, int], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        subject: User identifier (typically user ID)
        expires_delta: Optional custom expiration time. If not provided,
                      uses ACCESS_TOKEN_EXPIRE_MINUTES from settings.

    Returns:
        Signed JWT access token string
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode = {
        "sub": str(subject),
        "iat": datetime.now(timezone.utc),
        "exp": expire,
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )

    return encoded_jwt


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Args:
        token: JWT token string to decode

    Returns:
        Decoded token claims dictionary

    Raises:
        InvalidTokenError: If token is invalid, expired, or has verification errors
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "require": ["exp", "sub", "iat"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
            },
            leeway=30  # 30 seconds clock skew tolerance
        )
        return payload
    except InvalidTokenError:
        # PyJWT raises InvalidTokenError for all validation failures
        raise InvalidTokenError("Invalid authentication credentials")
