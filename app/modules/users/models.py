"""
User Model for E-Commerce application.
"""
from sqlalchemy import Column, Integer, String, DateTime, Index, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base, IdType


class User(Base):
    """
    User model representing user accounts and authentication information.
    """
    __tablename__ = "users"

    id = Column(
        IdType,
        primary_key=True,
        autoincrement=True,
        comment="Unique identifier for the user"
    )
    name = Column(
        String(150),
        nullable=False,
        comment="User's full name"
    )
    email = Column(
        String(255),
        nullable=False,
        unique=True,
        comment="User's email address (unique)"
    )
    password_hash = Column(
        String(255),
        nullable=False,
        comment="Hashed password (never store plaintext)"
    )
    role = Column(
        String(20),
        nullable=False,
        default='user',
        comment="User role: admin or user"
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default='1')
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="Timestamp when the user was created"
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment="Timestamp when the user was last updated"
    )

    # Relationship: User has many Orders
    # Note: No cascade delete since database uses RESTRICT to preserve historical orders
    orders = relationship(
        "Order",
        back_populates="user"
    )

    # Relationship: User has many Favorites
    # Note: Cascade delete is appropriate since favorites are not historical records
    # passive_deletes=True allows database FK CASCADE to handle deletion while ORM tracks orphans
    favorites = relationship(
        "Favorite",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    # Index for role filtering
    __table_args__ = (
        Index("idx_users_role", "role"),
    )

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
