import logging
from app.core.errors import AppError
from app.core.schemas import paginate
from app.modules.notifications import repository

log=logging.getLogger(__name__)
def notify(db,user_id,title,message):return repository.create(db,user_id,title,message)
def safe_notify(db,user_id,title,message):
    try:notify(db,user_id,title,message)
    except Exception:db.rollback();log.exception('Notification failed for user %s',user_id)
def clear_user(db,user_id):repository.clear_user(db,user_id)
def list_notifications(db,user_id,page,limit,unread=False):
    rows,total=repository.list_notifications(db,user_id,page,limit,unread)
    return paginate(rows,total,page,limit)
def read(db,id,user_id):
    n=repository.get(db,id)
    if n is None:raise AppError(404,'NOT_FOUND','Notification not found')
    if n.user_id!=user_id:raise AppError(403,'FORBIDDEN','You do not own this notification')
    n.is_read=True;db.commit();db.refresh(n);return n
def read_all(db,user_id):repository.read_all(db,user_id);return {'ok':True}
