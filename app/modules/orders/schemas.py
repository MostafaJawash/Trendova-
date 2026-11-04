from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import Field, ConfigDict
from app.core.schemas import StrictModel

class OrderLineIn(StrictModel):
    model_config=ConfigDict(extra='ignore')  # client supplied price is discarded
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=1000)
class OrderIn(StrictModel):
    items: list[OrderLineIn] = Field(min_length=1, max_length=50)
class StatusIn(StrictModel):
    status: Literal['pending','confirmed','shipped','delivered','cancelled']
class OrderLineOut(StrictModel):
    id: int; product_id: int; product_name: str | None; quantity: int; unit_price: Decimal; subtotal: Decimal
class OrderOut(StrictModel):
    id: int; user_id: int; total_amount: Decimal; status: str; reservation_id: str | None
    created_at: datetime; updated_at: datetime; items: list[OrderLineOut]
class OrderPage(StrictModel):
    items: list[OrderOut]; total: int; page: int; limit: int; pages: int
