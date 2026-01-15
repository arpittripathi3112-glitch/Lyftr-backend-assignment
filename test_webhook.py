"""
Tests for the POST /webhook endpoint.

Tests cover:
- Valid signature with message creation
- Duplicate message handling (idempotency)
- Invalid/missing signature (401)
- Validation errors (422)
"""

import os
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import SessionLocal, Base, engine


# Test configuration from environment
TEST_WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]


def compute_signature(body: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for request body."""
    return hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


@pytest.fixture(scope="function")
def client():
    """Create test client with fresh database for each test."""
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    with TestClient(app) as test_client:
        yield test_client
    
    # Cleanup - drop all tables after test
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def valid_message_body() -> str:
    """Return a valid message JSON body."""
    return '{"message_id":"m1","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"Hello"}'


@pytest.fixture
def valid_signature(valid_message_body: str) -> str:
    """Compute valid signature for test message."""
    return compute_signature(valid_message_body, TEST_WEBHOOK_SECRET)


class TestWebhookValidSignature:
    """Test webhook with valid signatures."""
    
    def test_create_message_success(self, client, valid_message_body, valid_signature):
        """Test successful message creation with valid signature."""
        response = client.post(
            "/webhook",
            content=valid_message_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": valid_signature
            }
        )
        
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    
    def test_duplicate_message_idempotent(self, client, valid_message_body, valid_signature):
        """Test that duplicate messages return 200 (idempotent)."""
        headers = {
            "Content-Type": "application/json",
            "X-Signature": valid_signature
        }
        
        # First request - creates message
        response1 = client.post("/webhook", content=valid_message_body, headers=headers)
        assert response1.status_code == 200
        assert response1.json() == {"status": "ok"}
        
        # Second request - duplicate, should still return 200
        response2 = client.post("/webhook", content=valid_message_body, headers=headers)
        assert response2.status_code == 200
        assert response2.json() == {"status": "ok"}
    
    def test_multiple_different_messages(self, client):
        """Test creating multiple different messages."""
        messages = [
            '{"message_id":"m1","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"Hello"}',
            '{"message_id":"m2","from":"+911234567890","to":"+14155550100","ts":"2025-01-15T10:01:00Z","text":"World"}',
            '{"message_id":"m3","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:02:00Z","text":"Test"}',
        ]
        
        for body in messages:
            signature = compute_signature(body, TEST_WEBHOOK_SECRET)
            response = client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature
                }
            )
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
    
    def test_message_without_text(self, client):
        """Test message without optional text field."""
        body = '{"message_id":"m_notext","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestWebhookInvalidSignature:
    """Test webhook with invalid or missing signatures."""
    
    def test_missing_signature_header(self, client, valid_message_body):
        """Test request without X-Signature header returns 401."""
        response = client.post(
            "/webhook",
            content=valid_message_body,
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid signature"}
    
    def test_invalid_signature(self, client, valid_message_body):
        """Test request with wrong signature returns 401."""
        response = client.post(
            "/webhook",
            content=valid_message_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": "invalid_signature_123"
            }
        )
        
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid signature"}
    
    def test_empty_signature(self, client, valid_message_body):
        """Test request with empty signature returns 401."""
        response = client.post(
            "/webhook",
            content=valid_message_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": ""
            }
        )
        
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid signature"}
    
    def test_signature_with_different_body(self, client, valid_signature):
        """Test signature computed for different body returns 401."""
        different_body = '{"message_id":"m2","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"Different"}'
        
        response = client.post(
            "/webhook",
            content=different_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": valid_signature  # Signature for m1, not m2
            }
        )
        
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid signature"}
    
    def test_signature_with_different_secret(self, client, valid_message_body):
        """Test signature computed with different secret returns 401."""
        wrong_signature = compute_signature(valid_message_body, "wrong_secret")
        
        response = client.post(
            "/webhook",
            content=valid_message_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": wrong_signature
            }
        )
        
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid signature"}


class TestWebhookValidationErrors:
    """Test webhook validation errors (422)."""
    
    def test_invalid_json(self, client):
        """Test invalid JSON returns 422."""
        body = "not valid json"
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_missing_message_id(self, client):
        """Test missing message_id returns 422."""
        body = '{"from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"Hello"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_empty_message_id(self, client):
        """Test empty message_id returns 422."""
        body = '{"message_id":"","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"Hello"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_invalid_from_format_no_plus(self, client):
        """Test 'from' without + prefix returns 422."""
        body = '{"message_id":"m1","from":"919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"Hello"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_invalid_from_format_with_letters(self, client):
        """Test 'from' with non-digit characters returns 422."""
        body = '{"message_id":"m1","from":"+91abc543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"Hello"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_invalid_to_format(self, client):
        """Test invalid 'to' format returns 422."""
        body = '{"message_id":"m1","from":"+919876543210","to":"14155550100","ts":"2025-01-15T10:00:00Z","text":"Hello"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_invalid_timestamp_no_z_suffix(self, client):
        """Test timestamp without Z suffix returns 422."""
        body = '{"message_id":"m1","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00","text":"Hello"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_invalid_timestamp_format(self, client):
        """Test invalid timestamp format returns 422."""
        body = '{"message_id":"m1","from":"+919876543210","to":"+14155550100","ts":"not-a-timestamp","text":"Hello"}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
    
    def test_text_too_long(self, client):
        """Test text exceeding 4096 characters returns 422."""
        long_text = "x" * 4097
        body = f'{{"message_id":"m1","from":"+919876543210","to":"+14155550100","ts":"2025-01-15T10:00:00Z","text":"{long_text}"}}'
        signature = compute_signature(body, TEST_WEBHOOK_SECRET)
        
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature
            }
        )
        
        assert response.status_code == 422
