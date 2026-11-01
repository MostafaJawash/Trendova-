"""
Pydantic Schemas for Order Item Model.
"""
from pydantic import BaseModel, ConfigDict
from decimal import Decimal


class OrderItemResponse(BaseModel):
    """Schema for order item response (read-only)."""
    id: int
    order_id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    subtotal: Decimal

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "order_id": 1,
                "product_id": 1,
                "quantity": 2,
                "unit_price": 99.99,
                "subtotal": 199.98
            }
        }
    )
