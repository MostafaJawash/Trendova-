from app.modules.notifications.models import Notification
def create(db,user_id,title,message):
    n=Notification(user_id=user_id,title=title,message=message)
    db.add(n);db.commit();db.refresh(n);return n
def list_notifications(db,user_id,page,limit,unread=False):
    q=db.query(Notification).filter_by(user_id=user_id)
    if unread:q=q.filter_by(is_read=False)
    return q.order_by(Notification.created_at.desc(),Notification.id.desc()).offset((page-1)*limit).limit(limit).all(),q.count()
def get(db,id):return db.get(Notification,id)
def clear_user(db,user_id):db.query(Notification).filter_by(user_id=user_id).delete();db.commit()
def read_all(db,user_id):db.query(Notification).filter_by(user_id=user_id,is_read=False).update({'is_read':True});db.commit()
