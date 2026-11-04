from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, Query, Form, File, UploadFile, Response
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import current, admin
from app.core.schemas import ERROR_RESPONSES
from app.modules.products import service
from app.modules.products.schemas import CategoryIn, CategoryUpdate, CategoryOut, CategoryPage, ProductOut, ProductDetail, AdminProductDetail, ProductPage, StockIn, StockOut, FavoriteOut, FavoritePage

categories_router=APIRouter(prefix='/categories',tags=['categories'],responses=ERROR_RESPONSES)
router=APIRouter(prefix='/products',tags=['products'],responses=ERROR_RESPONSES)
favorites_router=APIRouter(prefix='/favorites',tags=['favorites'],responses=ERROR_RESPONSES)

@categories_router.get('',response_model=CategoryPage,summary='List categories',description='Paginated category list.')
def categories(page:int=Query(1,ge=1),limit:int=Query(10,ge=1,le=100),_=Depends(current),db:Session=Depends(get_db)):
    return service.categories(db,page,limit)
@categories_router.post('',status_code=201,response_model=CategoryOut,summary='Create category',description='Admin creates a unique category.')
def create_category(data:CategoryIn,_=Depends(admin),db:Session=Depends(get_db)):
    return service.create_category(db,data)
@categories_router.put('/{category_id}',response_model=CategoryOut,summary='Update category',description='Admin updates category fields.')
def update_category(category_id:int,data:CategoryUpdate,_=Depends(admin),db:Session=Depends(get_db)):
    return service.update_category(db,category_id,data)
@categories_router.delete('/{category_id}',status_code=204,response_model=None,summary='Delete category',description='Admin removes an unused category.')
def delete_category(category_id:int,_=Depends(admin),db:Session=Depends(get_db)):
    service.delete_category(db,category_id);return Response(status_code=204)

@router.get('',response_model=ProductPage,summary='List products',description='Search, filter, sort and paginate active products.')
def products(search:str|None=None,category:int|None=None,min_price:Decimal|None=Query(None,alias='minPrice'),max_price:Decimal|None=Query(None,alias='maxPrice'),sort_by:Literal['price','name','created_at']='created_at',order:Literal['asc','desc']='desc',page:int=Query(1,ge=1),limit:int=Query(10,ge=1,le=100),auth=Depends(current),db:Session=Depends(get_db)):
    return service.products(db,auth[0].id,page,limit,search=search,category_id=category,min_price=min_price,max_price=max_price,sort_by=sort_by,order=order)
@router.get('/{product_id}',response_model=AdminProductDetail | ProductDetail,summary='Get product',description='Product, category and live inventory status.')
def product(product_id:int,auth=Depends(current),db:Session=Depends(get_db)):
    return service.product(db,product_id,auth[0].id,auth[0].role=='admin')
@router.post('',status_code=201,response_model=ProductOut,summary='Create product',description='Admin creates a product and initial inventory.')
def create_product(name:str=Form(...,min_length=1,max_length=200),description:str|None=Form(None),price:Decimal=Form(...,gt=0),category_id:int=Form(...,gt=0),initial_quantity:int=Form(0,ge=0),image:UploadFile|None=File(None),_=Depends(admin),db:Session=Depends(get_db)):
    return service.create_product(db,{'name':name,'description':description,'price':price,'category_id':category_id},image,initial_quantity)
@router.put('/{product_id}/stock',response_model=StockOut,summary='Set stock',description='Admin changes warehouse stock through the gateway.')
def set_stock(product_id:int,data:StockIn,_=Depends(admin),db:Session=Depends(get_db)):
    return service.set_stock(db,product_id,data.quantity)
@router.put('/{product_id}',response_model=ProductOut,summary='Update product',description='Admin updates product fields or image.')
def update_product(product_id:int,name:str|None=Form(None,min_length=1,max_length=200),description:str|None=Form(None),price:Decimal|None=Form(None,gt=0),category_id:int|None=Form(None,gt=0),image:UploadFile|None=File(None),_=Depends(admin),db:Session=Depends(get_db)):
    data={k:v for k,v in {'name':name,'description':description,'price':price,'category_id':category_id}.items() if v is not None}
    return service.update_product(db,product_id,data,image)
@router.delete('/{product_id}',status_code=204,response_model=None,summary='Delete product',description='Soft deletes an active product.')
def delete_product(product_id:int,_=Depends(admin),db:Session=Depends(get_db)):
    service.delete_product(db,product_id);return Response(status_code=204)

@favorites_router.get('',response_model=FavoritePage,summary='List favorites',description='Current user active favorites.')
def favorites(page:int=Query(1,ge=1),limit:int=Query(10,ge=1,le=100),auth=Depends(current),db:Session=Depends(get_db)):
    return service.favorites(db,auth[0].id,page,limit)
@favorites_router.post('/{product_id}',response_model=FavoriteOut,summary='Add favorite',description='Idempotently favorites an active product.')
def add_favorite(product_id:int,response:Response,auth=Depends(current),db:Session=Depends(get_db)):
    favorite,created=service.add_favorite(db,auth[0].id,product_id);response.status_code=201 if created else 200;return favorite
@favorites_router.delete('/{product_id}',status_code=204,response_model=None,summary='Remove favorite',description='Removes the current user favorite.')
def delete_favorite(product_id:int,auth=Depends(current),db:Session=Depends(get_db)):
    service.delete_favorite(db,auth[0].id,product_id);return Response(status_code=204)
