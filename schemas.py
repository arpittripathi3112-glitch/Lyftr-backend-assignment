"""
Pydantic schemas for request/response validation.

This module contains:
- Request models for incoming data validation
- Response models for API responses
- Query parameter models for filtering/pagination
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Pydantic Request Models
# =============================================================================

class WebhookRequest(BaseModel):
    """
    Pydantic model for validating incoming webhook requests.
    
    Validates:
    - message_id: non-empty string
    - from/to: E.164-like format (starts with +, then digits only)
    - ts: ISO-8601 UTC string with Z suffix
    - text: optional, max 4096 characters
    """
    message_id: str = Field(
        ...,
        min_length=1,
        description="Unique message identifier"
    )
    # Note: 'from' is a reserved word in Python, so we use alias
    from_msisdn: str = Field(
        ...,
        alias="from",
        description="Sender phone number in E.164 format"
    )
    to: str = Field(
        ...,
        description="Recipient phone number in E.164 format"
    )
    ts: str = Field(
        ...,
        description="Message timestamp in ISO-8601 UTC format (e.g., 2025-01-15T10:00:00Z)"
    )
    text: Optional[str] = Field(
        None,
        max_length=4096,
        description="Message text content"
    )

    @field_validator("from_msisdn", "to")
    @classmethod
    def validate_e164_format(cls, v: str, info) -> str:
        """Validate E.164-like phone number format: starts with +, then digits only."""
        if not v.startswith("+"):
            raise ValueError(f"{info.field_name} must start with '+'")
        if not v[1:].isdigit():
            raise ValueError(f"{info.field_name} must contain only digits after '+'")
        if len(v) < 2:
            raise ValueError(f"{info.field_name} must have at least one digit after '+'")
        return v

    @field_validator("ts")
    @classmethod
    def validate_iso8601_utc(cls, v: str) -> str:
        """Validate ISO-8601 UTC timestamp with Z suffix."""
        if not v.endswith("Z"):
            raise ValueError("ts must end with 'Z' (UTC timezone)")
        try:
            # Validate the format by parsing
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("ts must be a valid ISO-8601 UTC timestamp (e.g., 2025-01-15T10:00:00Z)")
        return v

    model_config = {
        "populate_by_name": True,  # Allow both 'from' and 'from_msisdn'
        "json_schema_extra": {
            "examples": [
                {
                    "message_id": "m1",
                    "from": "+919876543210",
                    "to": "+14155550100",
                    "ts": "2025-01-15T10:00:00Z",
                    "text": "Hello"
                }
            ]
        }
    }


# =============================================================================
# Pydantic Response Models
# =============================================================================

class WebhookResponse(BaseModel):
    """Response model for successful webhook processing."""
    status: str = Field(default="ok", description="Operation status")


class ErrorResponse(BaseModel):
    """Response model for error responses."""
    detail: str = Field(..., description="Error description")


class MessageResponse(BaseModel):
    """
    Response model for a single message in the messages list.
    Maps database fields to API response format.
    """
    message_id: str = Field(..., description="Unique message identifier")
    from_msisdn: str = Field(
        ...,
        alias="from",
        serialization_alias="from",
        description="Sender phone number"
    )
    to: str = Field(..., description="Recipient phone number")
    ts: str = Field(..., description="Message timestamp")
    text: Optional[str] = Field(None, description="Message content")

    model_config = {
        "populate_by_name": True,
        "from_attributes": True,  # Allow creating from ORM objects
    }


class MessagesListResponse(BaseModel):
    """
    Response model for GET /messages endpoint with pagination.
    
    Contains:
    - data: list of messages matching filters
    - total: total count of messages matching filters (ignoring pagination)
    - limit: number of messages per page
    - offset: starting position
    """
    data: list[MessageResponse] = Field(
        default_factory=list,
        description="List of messages"
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total messages matching filters (ignoring limit/offset)"
    )
    limit: int = Field(
        ...,
        ge=1,
        le=100,
        description="Maximum messages per page"
    )
    offset: int = Field(
        ...,
        ge=0,
        description="Number of messages skipped"
    )


class SenderCount(BaseModel):
    """Model for sender message count in stats."""
    from_msisdn: str = Field(
        ...,
        alias="from",
        serialization_alias="from",
        description="Sender phone number"
    )
    count: int = Field(..., ge=0, description="Number of messages from this sender")

    model_config = {"populate_by_name": True}


class StatsResponse(BaseModel):
    """
    Response model for GET /stats endpoint.
    
    Provides message-level analytics:
    - total_messages: total count of all messages
    - senders_count: number of unique senders
    - messages_per_sender: top 10 senders by message count
    - first_message_ts: timestamp of earliest message
    - last_message_ts: timestamp of latest message
    """
    total_messages: int = Field(
        ...,
        ge=0,
        description="Total number of messages"
    )
    senders_count: int = Field(
        ...,
        ge=0,
        description="Number of unique senders"
    )
    messages_per_sender: list[SenderCount] = Field(
        default_factory=list,
        description="Top 10 senders sorted by message count (descending)"
    )
    first_message_ts: Optional[str] = Field(
        None,
        description="Timestamp of the first message (null if no messages)"
    )
    last_message_ts: Optional[str] = Field(
        None,
        description="Timestamp of the last message (null if no messages)"
    )


class HealthResponse(BaseModel):
    """Response model for health check endpoints."""
    status: str = Field(..., description="Health status")
    reason: Optional[str] = Field(None, description="Reason if not ready")


# =============================================================================
# Query Parameter Models
# =============================================================================

class MessagesQueryParams(BaseModel):
    """
    Query parameters for GET /messages endpoint.
    
    Supports pagination and filtering.
    """
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of messages to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of messages to skip"
    )
    from_msisdn: Optional[str] = Field(
        default=None,
        alias="from",
        description="Filter by sender (exact match)"
    )
    since: Optional[str] = Field(
        default=None,
        description="Filter messages with ts >= since (ISO-8601 UTC)"
    )
    q: Optional[str] = Field(
        default=None,
        description="Free-text search in message text (case-insensitive)"
    )

    model_config = {"populate_by_name": True}
