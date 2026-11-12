from io import BytesIO
from pathlib import Path
from uuid import uuid4
from PIL import Image
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.errors import AppError
from app.core.schemas import paginate
from app.integrations.inventory import gateway as inventory_gateway
from app.integrations.inventory.gateway import InventoryUnavailableError
from app.core import cache, redis as rds
from app.modules.products import repository as repo


def _products_changed(product_id=None, actor_id=None):
    """Call only AFTER the DB commit succeeded: new list namespace, drop the detail key, RYW markers (actor + products)."""
    cache.invalidate_products(product_id); rds.mark_written(actor_id, products=True)


def _categories_changed(actor_id=None):
    cache.invalidate_categories(); rds.mark_written(actor_id, products=True)


def count_products(db):return repo.count_products(db)
def count_categories(db):return repo.count_categories(db)
def clear_user_favorites(db,user_id):repo.clear_user_favorites(db,user_id)
def get_active_products(db,ids):return {p.id:{'id':p.id,'name':p.name,'price':p.price} for p in repo.get_products(db,ids)}
def summary(p,favorite_ids=()):
    """`favorite_ids`: the product ids the current user favorited (from ONE query for the page), not a per-row relationship load."""
    return {'id':p.id,'category_id':p.category_id,'name':p.name,'description':p.description,'price':p.price,'image_url':p.image_url,'is_favorite':p.id in favorite_ids}
def category(db,id):
    c=repo.category(db,id)
    if c is None:raise AppError(404,'NOT_FOUND','Category not found')
    return c
def categories(db,page,limit):
    rows,total=repo.list_categories(db,page,limit);return paginate(rows,total,page,limit)
def create_category(db,data,actor_id=None):
    try:c=repo.create_category(db,data.model_dump())
    except IntegrityError:db.rollback();raise AppError(409,'CATEGORY_EXISTS','Category name already exists')
    _categories_changed(actor_id);return c
def update_category(db,id,data,actor_id=None):
    c=category(db,id)
    for k,v in data.model_dump(exclude_unset=True).items():setattr(c,k,v)
    try:db.commit();db.refresh(c)
    except IntegrityError:db.rollback();raise AppError(409,'CATEGORY_EXISTS','Category name already exists')
    _categories_changed(actor_id);return c
def delete_category(db,id,actor_id=None):
    c=category(db,id)
    if repo.any_in_category(db,id):raise AppError(409,'CATEGORY_HAS_PRODUCTS','Category has products')
    repo.delete_category(db,c);_categories_changed(actor_id)
def products(db,user_id,page,limit,**filters):
    lo=filters.get('min_price');hi=filters.get('max_price')
    if lo is not None and hi is not None and lo>hi:raise AppError(422,'VALIDATION_ERROR','minPrice cannot exceed maxPrice')
    cursor=filters.pop('cursor',None)
    sort_by=filters.get('sort_by','created_at');order=filters.get('order','desc')
    if cursor:
        try:filters['cursor']=repo.decode_cursor(cursor,sort_by,order)
        except ValueError:raise AppError(422,'INVALID_CURSOR','cursor is invalid or was issued for another sort order')
    rows,total=repo.list_products(db,page,limit,**filters)
    fav=repo.favorite_flags(db,user_id,[p.id for p in rows])
    result=paginate([summary(p,fav) for p in rows],total,page,limit)
    result['next_cursor']=repo.encode_cursor(sort_by,order,rows[-1]) if rows and len(rows)==limit else None   # additive field
    return result
def product(db,id,user_id,admin=False):
    p=repo.get_product(db,id)
    if p is None:raise AppError(404,'NOT_FOUND','Product not found')
    result=summary(p,repo.favorite_flags(db,user_id,[p.id]))
    result['category']={'id':p.category.id,'name':p.category.name} if p.category else None
    try:result['stock']={'quantity':inventory_gateway.gateway.get_quantity(p.id),'status':'available'}
    except InventoryUnavailableError:result['stock']={'quantity':None,'status':'unavailable'}
    if admin:result.update({'is_active':p.is_active,'created_at':p.created_at,'updated_at':p.updated_at})
    return result
def save_image(image):
    if image is None:return None
    raw=image.file.read(settings.max_upload_mb*1024*1024+1)
    if len(raw)>settings.max_upload_mb*1024*1024:raise AppError(422,'INVALID_IMAGE','Image exceeds size limit')
    try:
        im=Image.open(BytesIO(raw));im.verify();format_=im.format.lower()
        if format_ not in ('jpeg','png','webp'):raise ValueError()
    except Exception:raise AppError(422,'INVALID_IMAGE','Image must be a valid JPEG, PNG, or WebP')
    filename=f'{uuid4()}.{ "jpg" if format_=="jpeg" else format_ }'
    Path(settings.upload_dir,filename).write_bytes(raw)
    return '/media/'+filename
def create_product(db,data,image,quantity,actor_id=None):
    if data['price']<=0 or quantity<0:raise AppError(422,'VALIDATION_ERROR','Invalid price or quantity')
    if repo.category(db,data['category_id']) is None:raise AppError(422,'INVALID_CATEGORY','Category not found')
    url=save_image(image);data['image_url']=url;data['is_active']=True
    try:p=repo.create_product(db,data)
    except Exception:
        if url:Path(settings.upload_dir,url.split('/')[-1]).unlink(missing_ok=True)
        raise
    try:inventory_gateway.gateway.set_stock(p.id,quantity)
    except Exception:
        repo.delete_product(db,p)
        if url:Path(settings.upload_dir,url.split('/')[-1]).unlink(missing_ok=True)
        _products_changed(p.id,actor_id);raise AppError(503,'INVENTORY_UNAVAILABLE','Could not initialize inventory')
    _products_changed(p.id,actor_id);return summary(p)
def update_product(db,id,data,image,actor_id=None):
    p=repo.get_product(db,id)
    if p is None:raise AppError(404,'NOT_FOUND','Product not found')
    if 'price' in data and data['price']<=0:raise AppError(422,'VALIDATION_ERROR','Price must be positive')
    if 'category_id' in data and repo.category(db,data['category_id']) is None:raise AppError(422,'INVALID_CATEGORY','Category not found')
    old=p.image_url
    for k,v in data.items():setattr(p,k,v)
    if image:p.image_url=save_image(image)
    db.commit();db.refresh(p)
    if image and old:Path(settings.upload_dir,old.split('/')[-1]).unlink(missing_ok=True)
    _products_changed(id,actor_id);return summary(p)
def set_stock(db,id,quantity):
    if repo.get_product(db,id) is None:raise AppError(404,'NOT_FOUND','Product not found')
    try:inventory_gateway.gateway.set_stock(id,quantity)
    except InventoryUnavailableError:raise AppError(503,'INVENTORY_UNAVAILABLE','The warehouse service is temporarily unavailable. Please try again in a moment.',headers={'Retry-After':'2'})
    return {'product_id':id,'quantity':quantity}
def delete_product(db,id,actor_id=None):
    p=repo.get_product(db,id,active=False)
    if p is None:raise AppError(404,'NOT_FOUND','Product not found')
    p.is_active=False;db.commit();_products_changed(id,actor_id)
def favorites(db,user_id,page,limit):
    ids=repo.favorite_product_ids(db,user_id)
    active=repo.get_products(db,ids) if ids else []
    total=len(active)
    page_rows=active[(page-1)*limit:page*limit]
    return paginate([summary(p,{x.id for x in page_rows}) for p in page_rows],total,page,limit)
def add_favorite(db,user_id,id):
    f,created=_add_favorite(db,user_id,id);rds.mark_written(user_id);return f,created
def _add_favorite(db,user_id,id):
    if repo.get_product(db,id) is None:raise AppError(404,'NOT_FOUND','Product not found')
    f=repo.get_favorite(db,user_id,id)
    if f:return f,False
    try:return repo.create_favorite(db,user_id,id),True
    except IntegrityError:
        db.rollback();return repo.get_favorite(db,user_id,id),False
def delete_favorite(db,user_id,id):repo.delete_favorite(db,user_id,id);rds.mark_written(user_id)
