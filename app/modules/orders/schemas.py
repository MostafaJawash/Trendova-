"""
Pydantic Schemas for Order Model.
"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from decimal import Decimal
from enum import Enum


class OrderStatus(str, Enum):
    """Order status enumeration for Pydantic validation."""
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    PREPARING = "Preparing"
    DELIVERED = "Delivered"
    CANCELLED = "Cancelled"


class OrderResponse(BaseModel):
    """Schema for order response (read-only)."""
    id: int
    user_id: int
    total_amount: Decimal
    status: OrderStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "user_id": 1,
                "total_amount": 199.98,
                "status": "Pending",
                "created_at": "2026-11-01T09:00:00",
                "updated_at": "2026-11-01T09:00:00"
            }
        }
    )
