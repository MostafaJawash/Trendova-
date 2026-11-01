"""
Model registry - imports all models to ensure they are registered with SQLAlchemy Base.
This file should be imported at application startup to register all models.
"""
from app.core.database import Base

# Import all models to register them with Base
from app.modules.users.models import User
from app.modules.categories.models import Category
from app.modules.products.models import Product
from app.inventory_service.models import Inventory
from app.modules.orders.models import Order
from app.modules.order_items.models import OrderItem
from app.modules.favorites.models import Favorite

# Export all models for convenience
__all__ = [
    "Base",
    "User",
    "Category",
    "Product",
    "Inventory",
    "Order",
    "OrderItem",
    "Favorite",
]
