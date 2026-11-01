"""
Order Model for E-Commerce application.
"""
from enum import Enum as PyEnum
from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, Index, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class OrderStatus(str, PyEnum):
    """Order status enumeration."""
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    PREPARING = "Preparing"
    DELIVERED = "Delivered"
    CANCELLED = "Cancelled"


class Order(Base):
    """
    Order model representing customer orders.
    One User can have many Orders.
    """
    __tablename__ = "orders"

    id = Column(
        BigInteger,
        primary_key=True,
        unsigned=True,
        autoincrement=True,
        comment="Unique identifier for the order"
    )
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unsigned=True,
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
        default=OrderStatus.PENDING,
        comment="Order status"
    )
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
        Index("idx_orders_user_id", "user_id"),
        Index("idx_orders_status", "status"),
        CheckConstraint("total_amount >= 0", name="ck_orders_total_amount"),
    )

    def __repr__(self):
        return f"<Order(id={self.id}, user_id={self.user_id}, total={self.total_amount}, status={self.status})>"
