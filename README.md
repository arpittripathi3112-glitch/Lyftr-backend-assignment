# Lyftr-backend-assignment
This repository contains the backend service developed for the Lyftr assignment. The project focuses on setting up a simple API with health check endpoints and running it using Docker and Docker Compose.
# Architecture & Design Decisions
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   HTTP Client   │────▶│   FastAPI App   │────▶│     SQLite      │
│   (Webhooks)    │     │   + Middleware  │     │   (messages)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │  Prometheus     │
                        │  Metrics Store  │
                        └─────────────────┘
                        equest Lifecycle for POST /webhook
Request Lifecycle for POST /webhook
Request Received: Middleware generates a unique request_id (UUID) and starts latency timer
Raw Body Extraction: Body is read as raw bytes before any JSON parsing (required for signature verification)
Signature Validation: X-Signature header is verified against HMAC-SHA256(secret, raw_body)
JSON Parsing & Validation: Body is parsed as JSON and validated against Pydantic schema
Database Insert: Message is inserted with message_id as primary key (upsert semantics via IntegrityError handling)
Response: Returns {"status": "ok"} for both new inserts and duplicates (idempotent)
Logging & Metrics: Request details, latency, and outcome are logged and recorded
Why SQLite?
SQLite was chosen as specified in the requirements for several reasons:

Zero Configuration: No separate database server to manage
Persistence: Data file (/data/app.db) is stored on a Docker volume, surviving container restarts
Sufficient Performance: Handles thousands of rows efficiently for this use case
ACID Compliance: Supports transactions and uniqueness constraints for idempotency
The check_same_thread=False setting is required for SQLAlchemy to work correctly with FastAPI's async nature.

How Idempotency is Enforced
Idempotency is guaranteed through a two-layer approach:

Database Layer: message_id is the PRIMARY KEY of the messages table, making duplicate inserts impossible at the database level
Application Layer: SQLAlchemy's IntegrityError is caught gracefully when a duplicate is detected:
No stack traces or error responses
Returns 200 OK with {"status": "ok"} (same as successful insert)
Logs the duplicate detection for observability
Why HMAC Verification is Performed on Raw Body
The signature is computed over the raw request body bytes, not the parsed JSON:

Integrity: Ensures the exact bytes received match what the sender signed
Tamper Detection: Any modification (even whitespace changes) invalidates the signature
Timing Attack Prevention: Uses hmac.compare_digest() for constant-time comparison
Pagination and Deterministic Ordering Strategy
The /messages endpoint uses offset-based pagination with deterministic ordering:

Ordering: ORDER BY ts ASC, message_id ASC

Primary sort by timestamp ensures chronological order ("oldest first")
Secondary sort by message_id ensures determinism when timestamps are equal
This combination guarantees stable pagination results across requests
Pagination Contract:

limit: Controls page size (default: 50, min: 1, max: 100)
offset: Number of records to skip (default: 0, min: 0)
total: Always reflects the total count matching filters, ignoring pagination
#API Endpoints
POST /webhook
Ingests inbound WhatsApp-like messages with HMAC signature validation.

Request Headers:

Content-Type: application/json (required)
X-Signature: <hex> (required) - HMAC-SHA256 of raw body using WEBHOOK_SECRET
Request Body:
{
  "message_id": "m1",
  "from": "+919876543210",
  "to": "+14155550100",
  "ts": "2025-01-15T10:00:00Z",
  "text": "Hello"
}
Field Validation:

Field	Type	Required	Constraints
message_id	string	Yes	Non-empty
from	string	Yes	E.164 format: starts with +, followed by digits only
to	string	Yes	E.164 format: starts with +, followed by digits only
ts	string	Yes	ISO-8601 UTC with Z suffix (e.g., 2025-01-15T10:00:00Z)
text	string	No	Max 4096 characters
Response Codes:

Code	Description
200	Success (new message created OR duplicate detected)
401	Invalid or missing signature - {"detail": "invalid signature"}
422	Validation error (malformed JSON, missing fields, invalid formats)
Signature Behavior:

Missing X-Signature header → 401
Empty signature → 401
Wrong signature → 401
Signature computed with different body → 401
Signature computed with different secret → 401
Idempotency Behavior:

First valid request for message_id → Inserts row, returns 200
Subsequent requests with same message_id and valid signature → No insert, returns 200
Both cases return {"status": "ok"}
GET /messages
Lists stored messages with pagination and filtering.

Query Parameters:

Parameter	Type	Default	Constraints	Description
limit	int	50	1-100	Max messages per page
offset	int	0	≥ 0	Messages to skip
from	string	-	-	Filter by sender (exact match)
since	string	-	ISO-8601	Filter where ts >= since
q	string	-	-	Case-insensitive text search
Response:

{
  "data": [
    {
      "message_id": "m1",
      "from": "+919876543210",
      "to": "+14155550100",
      "ts": "2025-01-15T10:00:00Z",
      "text": "Hello"
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
Ordering Guarantee: Results are always ordered by ts ASC, message_id ASC (deterministic, oldest first).

GET /stats
Provides message-level analytics.

Response:

{
  "total_messages": 123,
  "senders_count": 10,
  "messages_per_sender": [
    { "from": "+919876543210", "count": 50 },
    { "from": "+911234567890", "count": 30 }
  ],
  "first_message_ts": "2025-01-10T09:00:00Z",
  "last_message_ts": "2025-01-15T10:00:00Z"
}
Fields:

total_messages: Total count of all stored messages
senders_count: Number of unique senders
messages_per_sender: Top 10 senders by message count (descending)
first_message_ts: Earliest message timestamp (null if empty)
last_message_ts: Latest message timestamp (null if empty)
Health Endpoints
GET /health/live
Liveness probe - always returns 200 once the application is running.

{"status": "ok"}
GET /health/ready
Readiness probe - returns 200 only when:

Database is reachable and schema is applied
WEBHOOK_SECRET is configured
Returns 503 otherwise with reason:

{"status": "not_ready", "reason": "WEBHOOK_SECRET not configured"}
GET /metrics
Exposes Prometheus-style metrics in text exposition format.

Metrics Exposed:

Metric	Type	Labels	Description
http_requests_total	Counter	method, path, status	Total HTTP requests
webhook_requests_total	Counter	result	Webhook outcomes
request_latency_seconds	Histogram	method, path	Request latency
Webhook Outcome Labels:

created: New message stored
duplicate: Message already existed (idempotent)
invalid_signature: HMAC validation failed
validation_error: Request body validation failed
Running the Project
Prerequisites
Docker and Docker Compose
Make (optional, for convenience commands)
Quick Start
Configure environment:

cp .env.example .env
# Edit .env and set WEBHOOK_SECRET to a secure value
Start the service:

make up
Verify it's running:

curl http://localhost:8000/health/ready
Makefile Commands
Command	Description
make up	Build and start in production mode (multi-worker)
make dev	Start in development mode with hot-reload
make down	Stop and remove all containers and volumes
make logs	Follow logs from the API service
make test	Run test suite locally
make test-docker	Run test suite inside Docker
Service URLs
Once running, the service is available at:

Health (Live): http://localhost:8000/health/live
Health (Ready): http://localhost:8000/health/ready
Webhook: http://localhost:8000/webhook
Messages: http://localhost:8000/messages
Stats: http://localhost:8000/stats
Metrics: http://localhost:8000/metrics
Logging & Observability
Structured JSON Logging
All logs are emitted as valid JSON (one object per line), suitable for log aggregation systems.

Log Fields:

Field	Description
ts	Server timestamp (ISO-8601 with Z suffix)
level	Log level (DEBUG, INFO, WARNING, ERROR)
request_id	Unique identifier per request (UUID)
method	HTTP method
path	Request path
status	Response status code
latency_ms	Request processing time in milliseconds
Request ID Usage
Every request is assigned a unique request_id (UUID):

Included in all log entries for the request
Returned in the X-Request-ID response header
Enables end-to-end request tracing
Webhook-Specific Log Fields
For /webhook requests, additional fields are logged:

Field	Description
message_id	Message ID from payload (when present)
dup	Boolean indicating duplicate detection
result	Outcome: created, duplicate, invalid_signature, validation_error
Example Log Entry:

{
  "ts": "2025-01-15T10:00:00.123Z",
  "level": "INFO",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "method": "POST",
  "path": "/webhook",
  "status": 200,
  "latency_ms": 12.34,
  "message_id": "m1",
  "dup": false,
  "result": "created"
}
Testing
Running Tests Locally
make test
This runs pytest with the test configuration from .env.test.

Running Tests in Docker
make test-docker
Test Coverage
The test suite covers:

Webhook Tests (test_webhook.py):

Valid signature with message creation
Duplicate message handling (idempotency)
Invalid/missing signature (401 responses)
Validation errors (422 responses)
E.164 phone number format validation
ISO-8601 timestamp validation
Text length limits
Messages Tests (test_messages.py):

Basic retrieval with default pagination
Pagination with limit and offset
Filtering by sender (from parameter)
Filtering by timestamp (since parameter)
Free-text search (q parameter)
Combined filters
Deterministic ordering verification
Stats Tests (test_stats.py):

Empty database returns zeros/nulls
Total messages count
Unique senders count
Top 10 senders by message count
First and last message timestamps
Setup Used
This project was developed using:

Editor: VSCode
AI Assistance: Claude (Anthropic) via GitHub Copilot
Project Structure
/app
├── main.py           # FastAPI app, middleware, routes
├── config.py         # Environment variable loading (pydantic-settings)
├── models.py         # SQLAlchemy ORM models
├── schemas.py        # Pydantic request/response schemas
├── storage.py        # Database operations (repository pattern)
├── utils.py          # HMAC signature verification
├── metrics.py        # Prometheus metrics helpers
└── logging_utils.py  # JSON logging setup and middleware

/tests
├── conftest.py       # Pytest fixtures
├── test_webhook.py   # Webhook endpoint tests
├── test_messages.py  # Messages endpoint tests
└── test_stats.py     # Stats endpoint tests

Dockerfile            # Multi-stage build
docker-compose.yml    # Service configuration with healthcheck
Makefile              # Convenience commands
requirements.txt      # Python dependencies
.env.example          # Environment template
