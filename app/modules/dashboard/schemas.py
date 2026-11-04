from decimal import Decimal
from typing import Any
from app.core.schemas import StrictModel
class DashboardOut(StrictModel):
    totals:dict[str,int]
    revenue:Decimal
    orders_by_status:dict[str,int]
    orders_last_7_days:list[dict[str,Any]]
    top_products:list[dict[str,Any]]
    recent_orders:list[dict[str,Any]]
