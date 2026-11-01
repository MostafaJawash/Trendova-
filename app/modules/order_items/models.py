"""
Order Item Model for E-Commerce application.
"""
from sqlalchemy import Column, BigInteger, Integer, Numeric, ForeignKey, UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class OrderItem(Base):
    """
    Order Item model representing individual products in an order.
    One Order can have multiple Order Items.
    One Product can appear in multiple Order Items.
    """
    __tablename__ = "order_items"

    id = Column(
        BigInteger,
        primary_key=True,
        unsigned=True,
        autoincrement=True,
        comment="Unique identifier for the order item"
    )
    order_id = Column(
        BigInteger,
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        unsigned=True,
        comment="Foreign key to orders table"
    )
    product_id = Column(
        BigInteger,
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        unsigned=True,
        comment="Foreign key to products table"
    )
    quantity = Column(
        Integer,
        nullable=False,
        unsigned=True,
        comment="Quantity of the product (must be > 0)"
    )
    unit_price = Column(
        Numeric(12, 2),
        nullable=False,
        comment="Unit price at time of purchase (historical)"
    )
    subtotal = Column(
        Numeric(14, 2),
        nullable=False,
        comment="Subtotal = quantity * unit_price"
    )

    # Relationship: Order Item belongs to one Order
    # Note: No cascade delete since database uses RESTRICT to preserve historical records
    order = relationship(
        "Order",
        back_populates="order_items"
    )

    # Relationship: Order Item references one Product
    product = relationship(
        "Product",
        back_populates="order_items"
    )

    # Unique constraint to prevent duplicate products in the same order
    # Also supports queries filtering by order_id
    # Check constraints for data validation
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
        Index("idx_order_items_product_id", "product_id"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price"),
        CheckConstraint("subtotal >= 0", name="ck_order_items_subtotal"),
    )

    def __repr__(self):
        return f"<OrderItem(id={self.id}, order_id={self.order_id}, product_id={self.product_id}, quantity={self.quantity})>"
