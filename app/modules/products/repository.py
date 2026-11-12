import base64
import json
from datetime import datetime
from decimal import Decimal
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
from app.modules.products.models import Product, Category, Favorite

def category(db, id): return db.get(Category, id)
def list_categories(db, page, limit):
    q = db.query(Category); return q.order_by(Category.id).offset((page-1)*limit).limit(limit).all(), q.count()
def create_category(db, data):
    c=Category(**data); db.add(c);db.commit();db.refresh(c);return c
def delete_category(db, c): db.delete(c);db.commit()
def count_categories(db): return db.query(Category).count()
def count_products(db): return db.query(Product).filter_by(is_active=True).count()
def active_in_category(db, id): return db.query(Product).filter_by(category_id=id, is_active=True).first() is not None
def any_in_category(db, id): return db.query(Product).filter_by(category_id=id).first() is not None
def get_product(db, id, active=True):
    q=db.query(Product).options(joinedload(Product.category)).filter(Product.id==id)
    if active:q=q.filter(Product.is_active.is_(True))
    return q.first()
def get_products(db, ids): return db.query(Product).filter(Product.id.in_(ids), Product.is_active.is_(True)).all()
def encode_cursor(sort_by,order,row):
    """Opaque keyset cursor = position of the last row of a page: (sort value, id)."""
    v=getattr(row,sort_by);v=v.isoformat() if isinstance(v,datetime) else str(v)
    return base64.urlsafe_b64encode(json.dumps([sort_by,order,v,row.id],separators=(',',':')).encode()).decode().rstrip('=')
def decode_cursor(cursor,sort_by,order):
    """-> (sort value, id); ValueError for anything that is not a cursor produced for this sort_by/order."""
    try:
        sb,od,v,last_id=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
        if sb!=sort_by or od!=order:raise ValueError('cursor belongs to another sort')
        return (datetime.fromisoformat(v) if sort_by=='created_at' else Decimal(v) if sort_by=='price' else str(v)),int(last_id)
    except Exception as exc:raise ValueError('invalid cursor') from exc
def list_products(db, page, limit, search=None, category_id=None, min_price=None, max_price=None, sort_by='created_at', order='desc', cursor=None):
    q=db.query(Product).filter(Product.is_active==True)  # noqa: E712  renders `is_active = true` (an index-usable predicate); `IS true` forces a filesort
    if search:
        pattern=f'%{search.lower()}%'
        q=q.filter(or_(func.lower(Product.name).like(pattern), func.lower(Product.description).like(pattern)))
    if category_id is not None:q=q.filter(Product.category_id==category_id)
    if min_price is not None:q=q.filter(Product.price>=min_price)
    if max_price is not None:q=q.filter(Product.price<=max_price)
    col=getattr(Product,sort_by)
    total=q.with_entities(func.count(Product.id)).order_by(None).scalar()   # plain SELECT count(id) ... (no derived-table wrapper)
    offset=(page-1)*limit
    if cursor is not None:   # keyset: seek past the last row of the previous page instead of skipping `offset` rows
        v,last_id=cursor;offset=0
        # OR form (not a row constructor): MySQL turns it into an index range scan, `(a,b) < (x,y)` is only applied as a filter
        if order=='desc':q=q.filter(or_(col<v,and_(col==v,Product.id<last_id)))   # ORDER BY col DESC, id DESC
        else:q=q.filter(or_(col>v,and_(col==v,Product.id<last_id)))               # ORDER BY col ASC, id DESC
    return q.order_by(col.asc() if order=='asc' else col.desc(),Product.id.desc()).offset(offset).limit(limit).all(),total
def create_product(db, data):
    p=Product(**data);db.add(p);db.commit();db.refresh(p);return p
def delete_product(db,p):db.delete(p);db.commit()
def get_favorite(db,user_id,product_id):return db.query(Favorite).filter_by(user_id=user_id,product_id=product_id).first()
def create_favorite(db,user_id,product_id):
    f=Favorite(user_id=user_id,product_id=product_id);db.add(f);db.commit();db.refresh(f);return f
def delete_favorite(db,user_id,product_id):db.query(Favorite).filter_by(user_id=user_id,product_id=product_id).delete();db.commit()
def clear_user_favorites(db,user_id): db.query(Favorite).filter_by(user_id=user_id).delete();db.commit()
def favorite_flags(db,user_id,product_ids):
    """Ids (among `product_ids`) that `user_id` has favorited: ONE query for the whole page (replaces the per-row joinedload)."""
    if not user_id or not product_ids:return set()
    return {r[0] for r in db.query(Favorite.product_id).filter(Favorite.user_id==user_id,Favorite.product_id.in_(list(product_ids))).all()}
def favorite_product_ids(db,user_id): return [r[0] for r in db.query(Favorite.product_id).filter_by(user_id=user_id).all()]
