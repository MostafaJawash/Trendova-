from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP, ForeignKey, Index
from sqlalchemy.sql import func
from app.core.database import Base, IdType
class Notification(Base):
    __tablename__='notifications'
    id=Column(IdType, primary_key=True, autoincrement=True)
    user_id=Column(IdType, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title=Column(String(150), nullable=False); message=Column(Text, nullable=False)
    is_read=Column(Boolean, nullable=False, default=False, server_default='0')
    created_at=Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.current_timestamp())
    __table_args__=(Index('idx_notifications_user_read_created','user_id','is_read','created_at'),)
