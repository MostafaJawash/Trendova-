"""
Pydantic Schemas for Inventory Model.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class InventoryResponse(BaseModel):
    """Schema for inventory response (read-only)."""
    id: int
    product_id: int
    total_quantity: int
    reserved_quantity: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "product_id": 1,
                "total_quantity": 100,
                "reserved_quantity": 10,
                "created_at": "2026-11-01T09:00:00",
                "updated_at": "2026-11-01T09:00:00"
            }
        }
    )


class InventoryResponseWithAvailable(InventoryResponse):
    """Schema for inventory response including calculated available quantity."""
    available_quantity: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "product_id": 1,
                "total_quantity": 100,
                "reserved_quantity": 10,
                "available_quantity": 90,
                "created_at": "2026-11-01T09:00:00",
                "updated_at": "2026-11-01T09:00:00"
            }
        }
    )
