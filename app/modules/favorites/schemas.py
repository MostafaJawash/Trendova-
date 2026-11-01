"""
Pydantic Schemas for Favorite Model.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class FavoriteResponse(BaseModel):
    """Schema for favorite response (read-only)."""
    id: int
    user_id: int
    product_id: int
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "user_id": 1,
                "product_id": 1,
                "created_at": "2026-11-01T09:00:00"
            }
        }
    )
