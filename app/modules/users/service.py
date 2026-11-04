from sqlalchemy.exc import IntegrityError
from app.core.errors import AppError
from app.core.security import hash_password, verify_password, create_access_token
from app.core.tokens import revoke
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.modules.users import repository

def get_by_id(db, user_id): return repository.get(db, user_id)
def count(db): return repository.count(db)
def seed_admin(db):
    if repository.by_email(db, settings.admin_email) is None:
        repository.create(db, settings.admin_full_name, settings.admin_email, hash_password(settings.admin_password), 'admin')
def register(db, data):
    if repository.by_email(db, data.email): raise AppError(409, 'EMAIL_EXISTS', 'Email already registered')
    try: return repository.create(db, data.name, data.email, hash_password(data.password), 'user')
    except IntegrityError: db.rollback(); raise AppError(409, 'EMAIL_EXISTS', 'Email already registered')
def login(db, data, ip):
    key = (ip, data.email.lower())
    retry = limiter.retry_after(key)
    if retry: raise AppError(429, 'TOO_MANY_ATTEMPTS', 'Too many failed attempts', headers={'Retry-After': str(retry)})
    user = repository.by_email(db, data.email)
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        limiter.failed(key)
        raise AppError(401, 'UNAUTHORIZED', 'Invalid email or password')
    limiter.clear(key)
    return {'access_token': create_access_token(user.id, user.role), 'token_type': 'bearer', 'expires_in': settings.access_token_expire_minutes*60, 'user': user}
def update_me(db, user, claims, data):
    if data.email and data.email.lower() != user.email.lower() and repository.by_email(db, data.email):
        raise AppError(409, 'EMAIL_EXISTS', 'Email already registered')
    if data.current_password and not verify_password(data.current_password, user.password_hash):
        raise AppError(400, 'INVALID_CURRENT_PASSWORD', 'Current password is invalid')
    if data.name is not None: user.name = data.name
    if data.email is not None: user.email = data.email
    if data.new_password: user.password_hash = hash_password(data.new_password)
    try: db.commit(); db.refresh(user)
    except IntegrityError: db.rollback(); raise AppError(409, 'EMAIL_EXISTS', 'Email already registered')
    if data.new_password: revoke(db, claims)
    return user
def list_users(db, page, limit, search=None, role=None): return repository.list_users(db, page, limit, search, role)
def delete_user(db, user_id, actor_id):
    if user_id == actor_id: raise AppError(409, 'CANNOT_DELETE_SELF', 'You cannot delete yourself')
    user = get_by_id(db, user_id)
    if user is None: raise AppError(404, 'NOT_FOUND', 'User not found')
    from app.modules.orders import service as orders
    from app.modules.products import service as products
    from app.modules.notifications import service as notifications
    if orders.has_orders(db, user_id): raise AppError(409, 'USER_HAS_ORDERS', 'User has orders')
    products.clear_user_favorites(db, user_id)
    notifications.clear_user(db, user_id)
    repository.remove(db, user)
