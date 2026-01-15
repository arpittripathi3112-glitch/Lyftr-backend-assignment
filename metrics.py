"""
Prometheus metrics for the webhook API.

This module provides:
- HTTP request counter (method, path, status)
- Webhook outcome counter (result)
- Request latency histogram (method, path)

Metrics are stored in-memory using prometheus-client.
"""

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST


# =============================================================================
# Metric Definitions
# =============================================================================

# HTTP request counter with labels for method, path, and status code
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=["method", "path", "status"]
)

# Webhook processing outcome counter
# result: created, duplicate, invalid_signature, validation_error
webhook_requests_total = Counter(
    "webhook_requests_total",
    "Total webhook processing outcomes",
    labelnames=["result"]
)

# Request latency histogram in seconds
# Using default buckets: .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0
request_latency_seconds = Histogram(
    "request_latency_seconds",
    "Request latency in seconds",
    labelnames=["method", "path"]
)


# =============================================================================
# Helper Functions
# =============================================================================

def record_http_request(method: str, path: str, status: int, latency_seconds: float) -> None:
    """
    Record an HTTP request in metrics.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path
        status: HTTP status code
        latency_seconds: Request processing time in seconds
    """
    # Normalize path to avoid high-cardinality labels
    # (e.g., /messages?limit=50 -> /messages)
    normalized_path = path.split("?")[0]
    
    http_requests_total.labels(
        method=method,
        path=normalized_path,
        status=str(status)
    ).inc()
    
    request_latency_seconds.labels(
        method=method,
        path=normalized_path
    ).observe(latency_seconds)


def record_webhook_outcome(result: str) -> None:
    """
    Record a webhook processing outcome.
    
    Args:
        result: Processing result - one of:
            - "created": New message stored
            - "duplicate": Message already existed (idempotent)
            - "invalid_signature": HMAC validation failed
            - "validation_error": Request body validation failed
    """
    webhook_requests_total.labels(result=result).inc()


def get_metrics() -> bytes:
    """
    Generate Prometheus exposition format metrics.
    
    Returns:
        Metrics in Prometheus text format as bytes
    """
    return generate_latest()


def get_metrics_content_type() -> str:
    """
    Get the content type for Prometheus metrics.
    
    Returns:
        Content type string for Prometheus exposition format
    """
    return CONTENT_TYPE_LATEST
