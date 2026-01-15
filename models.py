"""
SQLAlchemy ORM models for database tables.

This module contains database table definitions using SQLAlchemy.
For Pydantic request/response schemas, see schemas.py.
"""

from sqlalchemy import Column, String, Text

from app.storage import Base


class Message(Base):
    """
    SQLAlchemy model for storing WhatsApp-like messages.
    
    Table: messages
    Primary Key: message_id (ensures idempotency)
    """
    __tablename__ = "messages"

    message_id = Column(String, primary_key=True, index=True)
    from_msisdn = Column(String, nullable=False, index=True)
    to_msisdn = Column(String, nullable=False)
    ts = Column(String, nullable=False, index=True)  # ISO-8601 UTC string
    text = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)  # Server time ISO-8601
