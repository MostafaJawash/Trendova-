"""
Favorite Model for E-Commerce application.
"""
from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Favorite(Base):
    """
    Favorite model representing user's favorited products.
    A User can have multiple Favorites.
    A Product can be favorited by multiple Users.
    """
    __tablename__ = "favorites"

    id = Column(
        BigInteger,
        primary_key=True,
        unsigned=True,
        autoincrement=True,
        comment="Unique identifier for the favorite record"
    )
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unsigned=True,
        comment="Foreign key to users table"
    )
    product_id = Column(
        BigInteger,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unsigned=True,
        comment="Foreign key to products table"
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="Timestamp when the product was favorited"
    )

    # Relationship: Favorite belongs to one User
    user = relationship(
        "User",
        back_populates="favorites"
    )

    # Relationship: Favorite references one Product
    product = relationship(
        "Product",
        back_populates="favorites"
    )

    # Unique constraint to prevent duplicate user-product favorites
    # Also supports queries filtering by user_id (leading column)
    # Separate index on product_id for reverse lookups
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_favorites_user_product"),
        Index("idx_favorites_product_id", "product_id"),
    )

    def __repr__(self):
        return f"<Favorite(id={self.id}, user_id={self.user_id}, product_id={self.product_id})>"
