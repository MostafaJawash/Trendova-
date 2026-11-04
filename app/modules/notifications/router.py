from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import current
from app.core.schemas import ERROR_RESPONSES
from app.modules.notifications.schemas import NotificationOut, NotificationPage, ReadAllOut
from app.modules.notifications import service

router=APIRouter(prefix='/notifications',tags=['notifications'],responses=ERROR_RESPONSES)
@router.get('',response_model=NotificationPage,summary='List notifications',description='Paginated notifications belonging to the current user.')
def notifications(unread:bool=False,page:int=Query(1,ge=1),limit:int=Query(10,ge=1,le=100),auth=Depends(current),db:Session=Depends(get_db)):
    return service.list_notifications(db,auth[0].id,page,limit,unread)
@router.post('/read-all',response_model=ReadAllOut,summary='Read all notifications',description='Marks all current user notifications as read.')
def read_all(auth=Depends(current),db:Session=Depends(get_db)):
    return service.read_all(db,auth[0].id)
@router.patch('/{notification_id}/read',response_model=NotificationOut,summary='Read notification',description='Marks one owned notification as read.')
def read(notification_id:int,auth=Depends(current),db:Session=Depends(get_db)):
    return service.read(db,notification_id,auth[0].id)
