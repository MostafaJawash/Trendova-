"""
Pydantic Schemas for Category Model.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class CategoryBase(BaseModel):
    """Base Category schema with common fields."""
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)


class CategoryCreate(CategoryBase):
    """Schema for creating a new category."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Electronics",
                "description": "Electronic devices and accessories"
            }
        }
    )


class CategoryUpdate(BaseModel):
    """Schema for updating category information."""
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Electronics & Gadgets",
                "description": "Updated description"
            }
        }
    )


class CategoryResponse(CategoryBase):
    """Schema for category response."""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "name": "Electronics",
                "description": "Electronic devices and accessories",
                "created_at": "2026-11-01T09:00:00",
                "updated_at": "2026-11-01T09:00:00"
            }
        }
    )
