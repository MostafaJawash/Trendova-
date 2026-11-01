"""
Pydantic Schemas for Product Model.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from decimal import Decimal


class ProductBase(BaseModel):
    """Base Product schema with common fields."""
    category_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    price: Decimal = Field(..., ge=0, decimal_places=2, max_digits=12)
    image_url: Optional[str] = Field(None, max_length=500)


class ProductCreate(ProductBase):
    """Schema for creating a new product."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category_id": 1,
                "name": "Wireless Headphones",
                "description": "High-quality wireless headphones with noise cancellation",
                "price": 99.99,
                "image_url": "https://example.com/images/headphones.jpg"
            }
        }
    )


class ProductUpdate(BaseModel):
    """Schema for updating product information."""
    category_id: Optional[int] = Field(None, gt=0)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    price: Optional[Decimal] = Field(None, ge=0, decimal_places=2, max_digits=12)
    image_url: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Wireless Headphones Pro",
                "price": 129.99
            }
        }
    )


class ProductResponse(ProductBase):
    """Schema for product response (excludes inventory quantities)."""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "category_id": 1,
                "name": "Wireless Headphones",
                "description": "High-quality wireless headphones with noise cancellation",
                "price": 99.99,
                "image_url": "https://example.com/images/headphones.jpg",
                "created_at": "2026-11-01T09:00:00",
                "updated_at": "2026-11-01T09:00:00"
            }
        }
    )
