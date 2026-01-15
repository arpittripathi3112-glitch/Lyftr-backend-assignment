import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Response, Request, Depends, Header, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.storage import init_db, check_db_health, get_db, create_message, get_messages, get_stats
from app.logging_utils import setup_logging, RequestLoggingMiddleware, log_webhook_data
from app.utils import verify_hmac_signature
from app.metrics import record_webhook_outcome, get_metrics, get_metrics_content_type
from app.schemas import (
    HealthResponse,
    WebhookRequest,
    WebhookResponse,
    ErrorResponse,
    MessageResponse,
    MessagesListResponse,
    StatsResponse,
)


# Setup structured JSON logging
setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    - Startup: Initialize database and create tables
    - Shutdown: Cleanup resources
    """
    # Startup
    init_db()
    yield
    # Shutdown (cleanup if needed)


app = FastAPI(
    title="Webhook API",
    description="Production-style FastAPI service for WhatsApp-like messages",
    version="1.0.0",
    lifespan=lifespan,
)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)


# =============================================================================
# Health Check Routes
# =============================================================================

@app.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    """
    Liveness probe - always returns 200 once the app is running.
    Used by orchestrators to determine if the app needs to be restarted.
    """
    return HealthResponse(status="ok")


@app.get("/health/ready", response_model=HealthResponse)
async def health_ready(response: Response) -> HealthResponse:
    """
    Readiness probe - returns 200 only if:
    1. DB is reachable and schema is applied
    2. WEBHOOK_SECRET is set (non-empty)
    
    Otherwise returns 503 (Service Unavailable).
    """
    # Check if WEBHOOK_SECRET is set
    if not settings.WEBHOOK_SECRET:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            reason="WEBHOOK_SECRET not configured"
        )
    
    # Check if DB is reachable and schema is applied 
    if not check_db_health():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            reason="Database not reachable or schema not applied"
        )
    
    return HealthResponse(status="ready")


# =============================================================================
# Webhook Route
# =============================================================================

@app.post(
    "/webhook",
    response_model=WebhookResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid signature"},
        422: {"description": "Validation error"},
    }
)
async def webhook(
    request: Request,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
    db: Session = Depends(get_db)
) -> WebhookResponse:
    """
    Ingest inbound WhatsApp-like messages exactly once.

    - Validates HMAC-SHA256 signature using X-Signature header
    - Validates request body against WebhookRequest schema
    - Idempotent: duplicate message_id returns 200 without inserting

    Headers:
        - Content-Type: application/json
        - X-Signature: hex HMAC-SHA256 of raw body using WEBHOOK_SECRET
    """
    logger.info("Webhook request received")

    # Read raw body for signature verification
    raw_body = await request.body()
    logger.debug(f"Request body size: {len(raw_body)} bytes")

    # Verify X-Signature header is present
    if not x_signature:
        logger.error("Missing X-Signature header")
        record_webhook_outcome("invalid_signature")
        log_webhook_data(
            request=request,
            message_id=None,
            dup=False,
            result="invalid_signature"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature"
        )

    logger.debug("X-Signature header present, verifying HMAC")

    # Verify HMAC signature
    if not verify_hmac_signature(raw_body, x_signature, settings.WEBHOOK_SECRET):
        logger.error("Invalid HMAC signature")
        record_webhook_outcome("invalid_signature")
        log_webhook_data(
            request=request,
            message_id=None,
            dup=False,
            result="invalid_signature"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature"
        )

    logger.debug("HMAC signature verified successfully")

    # Parse and validate request body using Pydantic
    try:
        import json
        body_dict = json.loads(raw_body)
        logger.debug(f"Parsed JSON, message_id: {body_dict.get('message_id')}")
        webhook_data = WebhookRequest.model_validate(body_dict)
        logger.debug("Request body validated successfully")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        record_webhook_outcome("validation_error")
        log_webhook_data(
            request=request,
            message_id=None,
            dup=False,
            result="validation_error"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid JSON: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Validation error: {e}")
        record_webhook_outcome("validation_error")
        log_webhook_data(
            request=request,
            message_id=body_dict.get("message_id") if isinstance(body_dict, dict) else None,
            dup=False,
            result="validation_error"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )

    logger.debug(f"Inserting message into database: {webhook_data.message_id}")

    # Insert message into database (idempotent)
    success, is_duplicate = create_message(
        db=db,
        message_id=webhook_data.message_id,
        from_msisdn=webhook_data.from_msisdn,
        to_msisdn=webhook_data.to,
        ts=webhook_data.ts,
        text=webhook_data.text
    )

    if not success:
        logger.error(f"Failed to store message: {webhook_data.message_id}")
        log_webhook_data(
            request=request,
            message_id=webhook_data.message_id,
            dup=False,
            result="error"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store message"
        )

    # Log webhook result
    result = "duplicate" if is_duplicate else "created"
    logger.info(f"Message processed: {webhook_data.message_id}, result: {result}")
    record_webhook_outcome(result)
    log_webhook_data(
        request=request,
        message_id=webhook_data.message_id,
        dup=is_duplicate,
        result=result
    )

    return WebhookResponse(status="ok")


# =============================================================================
# Messages Route
# =============================================================================

@app.get(
    "/messages",
    response_model=MessagesListResponse,
)
async def list_messages(
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum number of messages to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of messages to skip")] = 0,
    from_param: Annotated[str | None, Query(alias="from", description="Filter by sender (exact match)")] = None,
    since: Annotated[str | None, Query(description="Filter messages with ts >= since (ISO-8601 UTC)")] = None,
    q: Annotated[str | None, Query(description="Free-text search in message text (case-insensitive)")] = None,
    db: Session = Depends(get_db)
) -> MessagesListResponse:
    """
    List stored messages with pagination and filtering.

    Query Parameters:
        - limit: Maximum messages per page (default 50, min 1, max 100)
        - offset: Number of messages to skip (default 0)
        - from: Filter by sender phone number (exact match)
        - since: Filter messages with ts >= since (ISO-8601 UTC timestamp)
        - q: Free-text search in message text (case-insensitive)

    Ordering:
        - Messages are ordered by ts ASC, message_id ASC (deterministic)

    Response:
        - data: List of messages matching filters
        - total: Total count of messages matching filters (ignoring limit/offset)
        - limit: The limit value used
        - offset: The offset value used
    """
    logger.info(f"GET /messages: limit={limit}, offset={offset}, from={from_param}, since={since}, q={q}")

    # Query messages from database
    messages, total = get_messages(
        db=db,
        limit=limit,
        offset=offset,
        from_msisdn=from_param,
        since=since,
        q=q
    )

    logger.debug(f"Retrieved {len(messages)} messages, total matching: {total}")

    # Convert ORM objects to response models
    data = [
        MessageResponse(
            message_id=msg.message_id,
            from_msisdn=msg.from_msisdn,
            to=msg.to_msisdn,
            ts=msg.ts,
            text=msg.text
        )
        for msg in messages
    ]

    logger.info(f"GET /messages: returned {len(data)} of {total} messages (limit={limit}, offset={offset})")

    return MessagesListResponse(
        data=data,
        total=total,
        limit=limit,
        offset=offset
    )


# =============================================================================
# Stats Route
# =============================================================================

@app.get(
    "/stats",
    response_model=StatsResponse,
)
async def get_statistics(
    db: Session = Depends(get_db)
) -> StatsResponse:
    """
    Provide simple message-level analytics.

    Response:
        - total_messages: Total count of all messages
        - senders_count: Number of unique senders
        - messages_per_sender: Top 10 senders sorted by count (descending)
        - first_message_ts: Timestamp of earliest message (null if no messages)
        - last_message_ts: Timestamp of latest message (null if no messages)
    """
    logger.info("GET /stats: computing statistics")

    # Query stats from database
    stats = get_stats(db)

    logger.debug(f"Stats result: {stats['total_messages']} messages, {stats['senders_count']} senders")
    logger.info(f"GET /stats: returned stats for {stats['total_messages']} messages")

    return StatsResponse(
        total_messages=stats["total_messages"],
        senders_count=stats["senders_count"],
        messages_per_sender=stats["messages_per_sender"],
        first_message_ts=stats["first_message_ts"],
        last_message_ts=stats["last_message_ts"]
    )


# =============================================================================
# Metrics Route
# =============================================================================

@app.get("/metrics")
async def metrics() -> Response:
    """
    Expose Prometheus-style metrics.
    
    Returns metrics in Prometheus text exposition format including:
    - http_requests_total: Total HTTP requests by method, path, status
    - webhook_requests_total: Webhook outcomes by result
    - request_latency_seconds: Request latency histogram
    """
    return Response(
        content=get_metrics(),
        media_type=get_metrics_content_type()
    )
