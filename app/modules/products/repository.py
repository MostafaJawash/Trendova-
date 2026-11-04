from sqlalchemy import func, or_
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
    q=db.query(Product).options(joinedload(Product.category),joinedload(Product.favorites)).filter(Product.id==id)
    if active:q=q.filter(Product.is_active.is_(True))
    return q.first()
def get_products(db, ids): return db.query(Product).filter(Product.id.in_(ids), Product.is_active.is_(True)).all()
def list_products(db, page, limit, search=None, category_id=None, min_price=None, max_price=None, sort_by='created_at', order='desc'):
    q=db.query(Product).options(joinedload(Product.favorites)).filter(Product.is_active.is_(True))
    if search:
        pattern=f'%{search.lower()}%'
        q=q.filter(or_(func.lower(Product.name).like(pattern), func.lower(Product.description).like(pattern)))
    if category_id is not None:q=q.filter(Product.category_id==category_id)
    if min_price is not None:q=q.filter(Product.price>=min_price)
    if max_price is not None:q=q.filter(Product.price<=max_price)
    col=getattr(Product,sort_by)
    return q.order_by(col.asc() if order=='asc' else col.desc(),Product.id.desc()).offset((page-1)*limit).limit(limit).all(),q.count()
def create_product(db, data):
    p=Product(**data);db.add(p);db.commit();db.refresh(p);return p
def delete_product(db,p):db.delete(p);db.commit()
def get_favorite(db,user_id,product_id):return db.query(Favorite).filter_by(user_id=user_id,product_id=product_id).first()
def create_favorite(db,user_id,product_id):
    f=Favorite(user_id=user_id,product_id=product_id);db.add(f);db.commit();db.refresh(f);return f
def delete_favorite(db,user_id,product_id):db.query(Favorite).filter_by(user_id=user_id,product_id=product_id).delete();db.commit()
def clear_user_favorites(db,user_id): db.query(Favorite).filter_by(user_id=user_id).delete();db.commit()
def favorite_product_ids(db,user_id): return [r[0] for r in db.query(Favorite.product_id).filter_by(user_id=user_id).all()]
