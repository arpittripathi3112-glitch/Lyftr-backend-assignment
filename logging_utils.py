import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from pythonjsonlogger import jsonlogger

from app.metrics import record_http_request


# Context variable to store request_id for the current request
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    """Get the current request ID from context."""
    return request_id_ctx.get()


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter to ensure ISO-8601 timestamps and request_id."""
    
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        # Ensure timestamp is in ISO-8601 format with Z suffix
        if not log_record.get('ts'):
            log_record['ts'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        log_record['level'] = record.levelname
        
        # Add request_id from context if available and not already present
        if 'request_id' not in log_record:
            req_id = request_id_ctx.get()
            if req_id:
                log_record['request_id'] = req_id


def setup_logging(log_level: str = "INFO"):
    """
    Setup structured JSON logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level.upper())

    # Remove existing handlers
    logger.handlers = []

    # Create JSON handler for stdout
    json_handler = logging.StreamHandler(sys.stdout)

    # Use custom JSON formatter
    formatter = CustomJsonFormatter(
        '%(ts)s %(level)s %(name)s %(message)s'
    )
    json_handler.setFormatter(formatter)

    logger.addHandler(json_handler)

    # Configure Uvicorn loggers to use JSON format
    uvicorn_loggers = [
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ]

    for logger_name in uvicorn_loggers:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.addHandler(json_handler)
        uvicorn_logger.propagate = False

    # Disable uvicorn.access logger since we have our own middleware
    logging.getLogger("uvicorn.access").disabled = True

    return logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests in structured JSON format.
    
    Required log keys:
    - ts: server time (ISO-8601)
    - level: log level
    - request_id: unique per request
    - method: HTTP method
    - path: request path
    - status: response status code
    - latency_ms: request processing time in milliseconds
    
    For /webhook requests, also includes:
    - message_id: from request body (when present)
    - dup: boolean indicating duplicate message
    - result: processing result (created, duplicate, invalid_signature, validation_error)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Set request_id in context for all loggers to use
        token = request_id_ctx.set(request_id)
        
        # Record start time
        start_time = time.time()
        
        try:
            # Process request
            response = await call_next(request)
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            
            # Calculate latency
            latency_ms = round((time.time() - start_time) * 1000, 2)
            latency_seconds = (time.time() - start_time)
            
            # Record metrics (exclude /metrics endpoint to avoid self-instrumentation noise)
            if request.url.path != "/metrics":
                record_http_request(
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    latency_seconds=latency_seconds
                )
            
            # Build log data
            log_data = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": latency_ms,
            }
            
            # Add webhook-specific fields if present in request state
            if hasattr(request.state, "webhook_log_data"):
                log_data.update(request.state.webhook_log_data)
            
            # Log the request
            logger = logging.getLogger("app.requests")
            
            if response.status_code >= 500:
                logger.error("Request completed", extra=log_data)
            elif response.status_code >= 400:
                logger.warning("Request completed", extra=log_data)
            else:
                logger.info("Request completed", extra=log_data)
            
            return response
        finally:
            # Reset context
            request_id_ctx.reset(token)


def log_webhook_data(request: Request, message_id: str = None, dup: bool = False, result: str = None):
    """
    Attach webhook-specific logging data to the request state.
    This data will be included in the request log by the middleware.
    
    Args:
        request: FastAPI request object
        message_id: Message ID from the webhook payload
        dup: Whether this is a duplicate message
        result: Processing result (created, duplicate, invalid_signature, validation_error)
    """
    webhook_data = {}
    
    if message_id is not None:
        webhook_data["message_id"] = message_id
    
    if result is not None:
        webhook_data["result"] = result
    
    webhook_data["dup"] = dup
    
    request.state.webhook_log_data = webhook_data
