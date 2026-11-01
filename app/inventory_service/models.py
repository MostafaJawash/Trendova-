"""
Inventory Model for E-Commerce application.
This model remains in the main database but is structured for future
extraction to an independent Warehouse Service.
"""
from sqlalchemy import Column, BigInteger, Integer, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Inventory(Base):
    """
    Inventory model representing stock information for products.
    One Product has at most one Inventory record (One-to-One).
    """
    __tablename__ = "inventory"

    id = Column(
        BigInteger,
        primary_key=True,
        unsigned=True,
        autoincrement=True,
        comment="Unique identifier for the inventory record"
    )
    product_id = Column(
        BigInteger,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unsigned=True,
        unique=True,
        comment="Foreign key to products table (unique - one-to-one)"
    )
    total_quantity = Column(
        Integer,
        nullable=False,
        unsigned=True,
        default=0,
        comment="Total quantity in stock (non-negative)"
    )
    reserved_quantity = Column(
        Integer,
        nullable=False,
        unsigned=True,
        default=0,
        comment="Quantity reserved for orders (non-negative)"
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="Timestamp when the inventory record was created"
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment="Timestamp when the inventory record was last updated"
    )

    # Relationship: Inventory belongs to one Product (One-to-One)
    product = relationship(
        "Product",
        back_populates="inventory"
    )

    # Unique constraint to enforce one-to-one relationship
    # Check constraint to ensure reserved_quantity <= total_quantity
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_inventory_product_id"),
        CheckConstraint("reserved_quantity <= total_quantity", name="ck_inventory_reserved_not_exceed_total"),
    )

    @property
    def available_quantity(self):
        """
        Calculate available quantity.
        available_quantity = total_quantity - reserved_quantity
        """
        return self.total_quantity - self.reserved_quantity

    def __repr__(self):
        return f"<Inventory(id={self.id}, product_id={self.product_id}, total={self.total_quantity}, reserved={self.reserved_quantity})>"
