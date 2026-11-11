from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, delete
from app.core.database import Base

class RevokedToken(Base):
    __tablename__ = 'revoked_tokens'
    jti = Column(String(64), primary_key=True)
    expires_at = Column(DateTime, nullable=False)

def purge_expired(db):
    """Housekeeping only: an expired JWT is rejected by its own `exp`, so purging is never
    needed for correctness. Runs from a periodic background task, not on the request path."""
    result=db.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(timezone.utc).replace(tzinfo=None)))
    db.commit()
    return result.rowcount

def is_revoked(db, jti):
    return db.get(RevokedToken, jti) is not None

def revoke(db, claims):
    db.add(RevokedToken(jti=claims['jti'], expires_at=datetime.fromtimestamp(claims['exp'], timezone.utc).replace(tzinfo=None)))
    db.commit()
