import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from app.core.errors import AppError
from app.core.schemas import paginate
from app.integrations.inventory import gateway as inventory_gateway
from app.integrations.inventory.gateway import InventoryUnavailableError
from app.modules.orders import repository as repo
from app.modules.products import service as products
from app.modules.notifications import service as notifications

log=logging.getLogger(__name__)
def has_orders(db,user_id):return repo.has_orders(db,user_id)
def count(db):return repo.count(db)
def stats(db):
    today=datetime.now(timezone.utc).date(); start=today-timedelta(days=6)
    counts={str(k):v for k,v in repo.last_days(db,start).items()}
    return {'orders':repo.count(db),'revenue':repo.revenue(db),'orders_by_status':{s:repo.by_status(db).get(s,0) for s in ('pending','confirmed','shipped','delivered','cancelled')},'orders_last_7_days':[{'date':(start+timedelta(days=n)).isoformat(),'count':counts.get((start+timedelta(days=n)).isoformat(),0)} for n in range(7)],'top_products':[{'product_id':r[0],'name':r[1],'quantity':int(r[2])} for r in repo.top_products(db)],'recent_orders':[serialize(o) for o in repo.recent(db)]}
def serialize(order):
    return {'id':order.id,'user_id':order.user_id,'total_amount':order.total_amount,'status':order.status,'reservation_id':order.reservation_id,'created_at':order.created_at,'updated_at':order.updated_at,'items':[{'id':i.id,'product_id':i.product_id,'product_name':i.product_name,'quantity':i.quantity,'unit_price':i.unit_price,'subtotal':i.subtotal} for i in order.order_items]}
def create(db,user_id,data):
    merged={}
    for item in data.items:merged[item.product_id]=merged.get(item.product_id,0)+item.quantity
    if any(q>1000 for q in merged.values()):raise AppError(422,'VALIDATION_ERROR','Merged quantity must be at most 1000')
    found=products.get_active_products(db,list(merged))
    bad=[id for id in merged if id not in found]
    if bad:raise AppError(422,'INVALID_PRODUCTS','Products do not exist or are inactive',bad)
    reservation_id=str(uuid4())
    requested=[{'product_id':id,'quantity':q} for id,q in merged.items()]
    try:result=inventory_gateway.gateway.reserve(reservation_id,requested)
    except InventoryUnavailableError:raise AppError(503,'INVENTORY_UNAVAILABLE','The warehouse service is temporarily unavailable. Please try again in a moment.',headers={'Retry-After':'2'})
    if not result.success:
        details=[{**x,'name':found[x['product_id']]['name']} for x in result.shortages]
        raise AppError(409,'INSUFFICIENT_STOCK','Insufficient stock',details)
    lines=[{'product_id':id,'name':found[id]['name'],'price':found[id]['price'],'quantity':q,'subtotal':found[id]['price']*q} for id,q in merged.items()]
    total=sum((x['subtotal'] for x in lines),Decimal('0'))
    try:order=repo.create(db,user_id,reservation_id,total,lines)
    except Exception:
        db.rollback()
        for attempt in range(3):
            try:inventory_gateway.gateway.release(reservation_id);break
            except Exception:
                if attempt==2:log.exception('Failed releasing reservation %s',reservation_id)
                else:time.sleep(0.05*(attempt+1))
        raise AppError(500,'ORDER_CREATE_FAILED','Order could not be saved; inventory reservation release attempted')
    notifications.safe_notify(db,user_id,'Order created',f'Your order #{order.id} was created')
    return serialize(order)
def list_orders(db,user_id,page,limit,status=None,filter_user_id=None):
    rows,total=repo.list_orders(db,user_id,page,limit,status,filter_user_id)
    return paginate([serialize(o) for o in rows],total,page,limit)
def get(db,id,user_id,is_admin):
    order=repo.get(db,id)
    if order is None:raise AppError(404,'NOT_FOUND','Order not found')
    if order.user_id!=user_id and not is_admin:raise AppError(403,'FORBIDDEN','You do not own this order')
    return serialize(order)
def change_status(db,id,status):
    order=repo.get(db,id)
    if order is None:raise AppError(404,'NOT_FOUND','Order not found')
    allowed={'pending':{'confirmed','cancelled'},'confirmed':{'shipped','cancelled'},'shipped':{'delivered'}}
    if status not in allowed.get(order.status,set()):raise AppError(409,'INVALID_STATUS_TRANSITION','Invalid status transition')
    order.status=status
    if status=='cancelled':
        try:inventory_gateway.gateway.release(order.reservation_id)
        except Exception:db.rollback();raise AppError(503,'INVENTORY_UNAVAILABLE','Could not release inventory')
    db.commit();db.refresh(order)
    notifications.safe_notify(db,order.user_id,'Order updated',f'Order #{order.id} is {status}')
    return serialize(order)
