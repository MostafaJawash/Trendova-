from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import current, admin
from app.core.schemas import ERROR_RESPONSES
from app.modules.orders.schemas import OrderIn, OrderOut, OrderPage, StatusIn
from app.modules.orders import service

router=APIRouter(prefix='/orders',tags=['orders'],responses=ERROR_RESPONSES)
@router.post('',status_code=201,response_model=OrderOut,summary='Create order',description='Reserves stock, saves price snapshots and notifies the owner.')
def create_order(data:OrderIn,auth=Depends(current),db:Session=Depends(get_db)):
    return service.create(db,auth[0].id,data)
@router.get('',response_model=OrderPage,summary='List orders',description='Users see their own orders; admins can filter all orders.')
def orders(status:str|None=None,user_id:int|None=None,page:int=Query(1,ge=1),limit:int=Query(10,ge=1,le=100),auth=Depends(current),db:Session=Depends(get_db)):
    actor=auth[0];is_admin=actor.role=='admin'
    return service.list_orders(db,None if is_admin else actor.id,page,limit,status,user_id if is_admin else None)
@router.get('/{order_id}',response_model=OrderOut,summary='Get order',description='Returns an order to its owner or admin.')
def order(order_id:int,auth=Depends(current),db:Session=Depends(get_db)):
    actor=auth[0];return service.get(db,order_id,actor.id,actor.role=='admin')
@router.patch('/{order_id}/status',response_model=OrderOut,summary='Change order status',description='Admin follows allowed transitions, releasing stock on cancellation.')
def status(order_id:int,data:StatusIn,_=Depends(admin),db:Session=Depends(get_db)):
    return service.change_status(db,order_id,data.status)
