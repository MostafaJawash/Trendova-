from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.modules.orders.models import Order, OrderItem

def create(db,user_id,reservation_id,total,lines):
    order=Order(user_id=user_id,reservation_id=reservation_id,total_amount=total,status='pending')
    db.add(order);db.flush()
    for line in lines:
        db.add(OrderItem(order_id=order.id,product_id=line['product_id'],product_name=line['name'],quantity=line['quantity'],unit_price=line['price'],subtotal=line['subtotal']))
    db.commit();db.refresh(order)
    return get(db,order.id)
def get(db,id):return db.query(Order).options(joinedload(Order.order_items)).filter_by(id=id).first()
def list_orders(db,user_id,page,limit,status=None,filter_user_id=None):
    q=db.query(Order).options(joinedload(Order.order_items))
    if user_id is not None:q=q.filter(Order.user_id==user_id)
    if filter_user_id is not None:q=q.filter(Order.user_id==filter_user_id)
    if status:q=q.filter(Order.status==status)
    total=q.count()
    return q.order_by(Order.created_at.desc(),Order.id.desc()).offset((page-1)*limit).limit(limit).all(),total
def has_orders(db,user_id):return db.query(Order).filter_by(user_id=user_id).first() is not None
def count(db):return db.query(Order).count()
def revenue(db):return db.query(func.coalesce(func.sum(Order.total_amount),0)).filter(Order.status!='cancelled').scalar()
def by_status(db):return dict(db.query(Order.status,func.count(Order.id)).group_by(Order.status).all())
def recent(db,n=5):return db.query(Order).options(joinedload(Order.order_items)).order_by(Order.created_at.desc(),Order.id.desc()).limit(n).all()
def last_days(db,start):return dict(db.query(func.date(Order.created_at),func.count(Order.id)).filter(Order.created_at>=start).group_by(func.date(Order.created_at)).all())
def top_products(db,n=5):return db.query(OrderItem.product_id,OrderItem.product_name,func.sum(OrderItem.quantity)).join(Order,Order.id==OrderItem.order_id).filter(Order.status!='cancelled').group_by(OrderItem.product_id,OrderItem.product_name).order_by(func.sum(OrderItem.quantity).desc()).limit(n).all()
