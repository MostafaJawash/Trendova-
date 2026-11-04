from sqlalchemy import func, or_
from app.modules.users.models import User

def get(db, user_id): return db.get(User, user_id)
def by_email(db, email): return db.query(User).filter(func.lower(User.email) == email.lower()).first()
def list_users(db, page, limit, search=None, role=None):
    q = db.query(User)
    if search:
        pattern = f'%{search.lower()}%'
        q = q.filter(or_(func.lower(User.email).like(pattern), func.lower(User.name).like(pattern)))
    if role: q = q.filter(User.role == role)
    total = q.count()
    return q.order_by(User.id).offset((page-1)*limit).limit(limit).all(), total
def count(db): return db.query(User).count()
def create(db, name, email, password_hash, role):
    u = User(name=name, email=email, password_hash=password_hash, role=role, is_active=True)
    db.add(u); db.commit(); db.refresh(u); return u
def remove(db, user): db.delete(user); db.commit()
