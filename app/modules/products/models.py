"""
Product Model for E-Commerce application.
"""
from sqlalchemy import Column, BigInteger, String, Text, Numeric, DateTime, ForeignKey, Index, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Product(Base):
    """
    Product model representing product catalog information.
    A Product belongs to one Category.
    One Product has at most one Inventory record.
    """
    __tablename__ = "products"

    id = Column(
        BigInteger,
        primary_key=True,
        unsigned=True,
        autoincrement=True,
        comment="Unique identifier for the product"
    )
    category_id = Column(
        BigInteger,
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        unsigned=True,
        comment="Foreign key to categories table"
    )
    name = Column(
        String(200),
        nullable=False,
        comment="Product name"
    )
    description = Column(
        Text,
        nullable=True,
        comment="Product description"
    )
    price = Column(
        Numeric(12, 2),
        nullable=False,
        comment="Product price (non-negative)"
    )
    image_url = Column(
        String(500),
        nullable=True,
        comment="URL to product image"
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="Timestamp when the product was created"
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment="Timestamp when the product was last updated"
    )

    # Relationship: Product belongs to one Category
    category = relationship(
        "Category",
        back_populates="products"
    )

    # Relationship: Product has one Inventory (One-to-One)
    # passive_deletes=True allows database FK CASCADE to handle deletion while ORM tracks orphans
    inventory = relationship(
        "Inventory",
        back_populates="product",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    # Relationship: Product can appear in multiple Order Items
    # Note: No cascade delete since database uses RESTRICT to preserve historical order items
    order_items = relationship(
        "OrderItem",
        back_populates="product"
    )

    # Relationship: Product can be favorited by multiple Users
    # Note: Cascade delete is appropriate since favorites are not historical records
    # passive_deletes=True allows database FK CASCADE to handle deletion while ORM tracks orphans
    favorites = relationship(
        "Favorite",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    # Index for category filtering and check constraint
    __table_args__ = (
        Index("idx_category_id", "category_id"),
        CheckConstraint("price >= 0", name="ck_products_price"),
    )

    def __repr__(self):
        return f"<Product(id={self.id}, name={self.name}, price={self.price})>"
