"""
Order Model for E-Commerce application.
"""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index, CheckConstraint, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base, IdType


class Order(Base):
    """
    Order model representing customer orders.
    One User can have many Orders.
    """
    __tablename__ = "orders"

    id = Column(
        IdType,
        primary_key=True,
        autoincrement=True,
        comment="Unique identifier for the order"
    )
    user_id = Column(
        IdType,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Foreign key to users table"
    )
    total_amount = Column(
        Numeric(14, 2),
        nullable=False,
        comment="Total order amount (non-negative)"
    )
    status = Column(
        String(30),
        nullable=False,
        default='pending',
        comment="Order status"
    )
    reservation_id = Column(String(36), nullable=True, unique=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="Timestamp when the order was created"
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment="Timestamp when the order was last updated"
    )

    # Relationship: Order belongs to one User
    user = relationship(
        "User",
        back_populates="orders"
    )

    # Relationship: Order has many Order Items
    # Note: No cascade delete since database uses RESTRICT to preserve historical records
    order_items = relationship(
        "OrderItem",
        back_populates="order"
    )

    # Index for user filtering, status filtering, and check constraint
    __table_args__ = (
        # idx_orders_user_id (user_id) was dropped by app/core/migrations_req3_indexes.py: idx_orders_user_created covers it
        # Req 3: "my orders" newest first without sorting the user's whole history
        Index("idx_orders_user_created", "user_id", "created_at", "id"),
        Index("idx_orders_status", "status"),
        CheckConstraint("total_amount >= 0", name="ck_orders_total_amount"),
    )

    def __repr__(self):
        return f"<Order(id={self.id}, user_id={self.user_id}, total={self.total_amount}, status={self.status})>"

class OrderItem(Base):
    __tablename__ = 'order_items'
    id = Column(IdType, primary_key=True, autoincrement=True)
    order_id = Column(IdType, ForeignKey('orders.id', ondelete='RESTRICT'), nullable=False)
    product_id = Column(IdType, ForeignKey('products.id', ondelete='RESTRICT'), nullable=False)
    product_name = Column(String(200))
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    order = relationship('Order', back_populates='order_items')
    product = relationship('Product', back_populates='order_items')
    __table_args__ = (UniqueConstraint('order_id', 'product_id', name='uq_order_items_order_product'), Index('idx_order_items_product_id', 'product_id'), CheckConstraint('quantity > 0', name='ck_order_items_quantity'), CheckConstraint('unit_price >= 0', name='ck_order_items_unit_price'), CheckConstraint('subtotal >= 0', name='ck_order_items_subtotal'))
