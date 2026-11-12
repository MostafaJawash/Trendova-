from fastapi import APIRouter, Depends, Request, Query, Response
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import current, admin, read_db
from app.core.tokens import revoke
from app.core.schemas import ERROR_RESPONSES, paginate
from app.modules.users.schemas import Register, Login, Profile, UserOut, TokenOut, UserPage
from app.modules.users import service

auth_router = APIRouter(prefix='/auth', tags=['auth'], responses=ERROR_RESPONSES)
router = APIRouter(prefix='/users', tags=['users'], responses=ERROR_RESPONSES)

@auth_router.post('/register', status_code=201, response_model=UserOut, summary='Register user', description='Creates a normal user; supplied role is ignored.')
def register(data: Register, db: Session = Depends(get_db)): return service.register(db, data)

@auth_router.post('/login', response_model=TokenOut, summary='Log in', description='Issues a bearer token after verifying credentials.')
def login(data: Login, request: Request, db: Session = Depends(get_db)):
    return service.login(db, data, request.client.host if request.client else '')

@auth_router.post('/logout', status_code=204, response_model=None, summary='Log out', description='Revokes the current token.')
def logout(auth=Depends(current), db: Session = Depends(get_db)):
    revoke(db, auth[1]); return Response(status_code=204)

@router.get('/me', response_model=UserOut, summary='Get my profile', description='Returns the authenticated user profile.')
@auth_router.get('/me', response_model=UserOut, summary='Get my profile', description='Returns the authenticated user profile.')
def me(auth=Depends(current)): return auth[0]

@router.put('/me', response_model=UserOut, summary='Update my profile', description='Password changes revoke the current token.')
@auth_router.put('/me', response_model=UserOut, summary='Update my profile', description='Password changes revoke the current token.')
def edit_me(data: Profile, auth=Depends(current), db: Session = Depends(get_db)):
    return service.update_me(db, auth[0], auth[1], data)

@router.get('', response_model=UserPage, summary='List users', description='Admin list with search, role and pagination.')
def users(page: int = Query(1, ge=1), limit: int = Query(10, ge=1, le=100), search: str | None = None, role: str | None = None, _=Depends(admin), db: Session = Depends(read_db)):
    items, total = service.list_users(db, page, limit, search, role)
    return paginate(items, total, page, limit)

@router.get('/{user_id}', response_model=UserOut, summary='Get user', description='Admin lookup by user id.')
def user(user_id: int, _=Depends(admin), db: Session = Depends(get_db)):
    from app.core.errors import AppError
    found = service.get_by_id(db, user_id)
    if found is None: raise AppError(404, 'NOT_FOUND', 'User not found')
    return found

@router.delete('/{user_id}', status_code=204, response_model=None, summary='Delete user', description='Deletes a user without orders.')
def delete_user(user_id: int, actor=Depends(admin), db: Session = Depends(get_db)):
    service.delete_user(db, user_id, actor.id)
    return Response(status_code=204)
