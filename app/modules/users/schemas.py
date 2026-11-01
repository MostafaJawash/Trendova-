"""
Pydantic Schemas for User Model.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class UserRole(str, Enum):
    """User role enumeration for Pydantic validation."""
    ADMIN = "admin"
    CUSTOMER = "customer"


class UserBase(BaseModel):
    """Base User schema with common fields."""
    name: str = Field(..., min_length=1, max_length=150)
    email: EmailStr


class UserCreate(UserBase):
    """Schema for creating a new user (public - defaults to customer role)."""
    password: str = Field(..., min_length=8, max_length=255)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "John Doe",
                "email": "john.doe@example.com",
                "password": "securepassword123"
            }
        }
    )


class UserUpdate(BaseModel):
    """Schema for updating user information (no password or role changes)."""
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    email: Optional[EmailStr] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "John Smith",
                "email": "john.smith@example.com"
            }
        }
    )


class UserResponse(UserBase):
    """Schema for user response (excludes password_hash)."""
    id: int
    role: UserRole
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "name": "John Doe",
                "email": "john.doe@example.com",
                "role": "customer",
                "created_at": "2026-11-01T09:00:00",
                "updated_at": "2026-11-01T09:00:00"
            }
        }
    )
