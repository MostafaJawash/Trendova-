from datetime import datetime, timedelta, timezone
from uuid import uuid4
import bcrypt, jwt
from app.core.config import settings
def hash_password(password): return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def verify_password(password, hashed):
    try: return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception: return False
def create_access_token(user_id, role):
    now=datetime.now(timezone.utc); exp=now+timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({'sub':str(user_id),'role':str(role),'jti':str(uuid4()),'iat':now,'exp':exp}, settings.secret_key, algorithm='HS256')
def decode_access_token(token): return jwt.decode(token, settings.secret_key, algorithms=['HS256'], options={'require':['sub','role','jti','iat','exp']})
