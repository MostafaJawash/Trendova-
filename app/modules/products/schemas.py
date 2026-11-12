from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import Field
from app.core.schemas import StrictModel

class CategoryIn(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
class CategoryUpdate(StrictModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    description: str | None = None
class CategoryOut(StrictModel):
    id: int; name: str; description: str | None; created_at: datetime; updated_at: datetime
class CategoryPage(StrictModel):
    items: list[CategoryOut]; total: int; page: int; limit: int; pages: int
class ProductOut(StrictModel):
    id: int; category_id: int; name: str; description: str | None; price: Decimal; image_url: str | None; is_favorite: bool = False
class ProductPage(StrictModel):
    items: list[ProductOut]; total: int; page: int; limit: int; pages: int
    next_cursor: str | None = None   # keyset pagination: pass it back as ?cursor= to get the next page
class ProductStockOut(ProductOut):
    stock: dict[str, Any]
class ProductStockPage(StrictModel):   # include_stock=true
    items: list[ProductStockOut]; total: int; page: int; limit: int; pages: int
    next_cursor: str | None = None
class ProductDetail(ProductOut):
    category: dict[str, Any] | None = None
    stock: dict[str, Any]
class AdminProductDetail(ProductDetail):
    is_active: bool
    created_at: datetime
    updated_at: datetime
class StockIn(StrictModel): quantity: int = Field(ge=0)
class StockOut(StrictModel): product_id: int; quantity: int
class FavoriteOut(StrictModel): id: int; user_id: int; product_id: int; created_at: datetime
class FavoritePage(StrictModel):
    items: list[ProductOut]; total: int; page: int; limit: int; pages: int
