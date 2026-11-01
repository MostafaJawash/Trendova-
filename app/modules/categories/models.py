"""
Category Model for E-Commerce application.
"""
from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Category(Base):
    """
    Category model representing product categories.
    One Category has many Products.
    """
    __tablename__ = "categories"

    id = Column(
        BigInteger,
        primary_key=True,
        unsigned=True,
        autoincrement=True,
        comment="Unique identifier for the category"
    )
    name = Column(
        String(150),
        nullable=False,
        unique=True,
        comment="Category name (unique)"
    )
    description = Column(
        Text,
        nullable=True,
        comment="Category description"
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="Timestamp when the category was created"
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment="Timestamp when the category was last updated"
    )

    # Relationship: One Category has many Products
    # Note: No cascade delete since database uses RESTRICT to prevent deleting categories with products
    products = relationship(
        "Product",
        back_populates="category"
    )

    def __repr__(self):
        return f"<Category(id={self.id}, name={self.name})>"
