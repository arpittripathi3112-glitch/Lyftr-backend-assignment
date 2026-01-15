"""
Tests for the GET /messages endpoint.

Tests cover:
- Basic retrieval with default pagination
- Pagination with limit and offset
- Filtering by sender (from)
- Filtering by timestamp (since)
- Free-text search (q)
- Combined filters
- Edge cases and empty results
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


def create_message(client, message_id: str, from_msisdn: str, to_msisdn: str, ts: str, text: str = None):
    """Helper to create a message via webhook."""
    import json
    body_dict = {
        "message_id": message_id,
        "from": from_msisdn,
        "to": to_msisdn,
        "ts": ts,
    }
    if text is not None:
        body_dict["text"] = text
    
    body = json.dumps(body_dict)
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
def seeded_client(client):
    """Client with pre-seeded messages for testing."""
    # Create test messages with different senders, timestamps, and text
    messages = [
        ("m1", "+919876543210", "+14155550100", "2025-01-15T10:00:00Z", "Hello world"),
        ("m2", "+919876543210", "+14155550100", "2025-01-15T10:01:00Z", "How are you?"),
        ("m3", "+911234567890", "+14155550100", "2025-01-15T10:02:00Z", "Goodbye"),
        ("m4", "+911234567890", "+14155550100", "2025-01-15T10:03:00Z", "See you later"),
        ("m5", "+919999999999", "+14155550100", "2025-01-15T10:04:00Z", "Hello there"),
        ("m6", "+919876543210", "+14155550100", "2025-01-15T10:05:00Z", None),  # No text
    ]
    
    for msg in messages:
        create_message(client, *msg)
    
    return client


class TestMessagesBasic:
    """Test basic messages retrieval."""
    
    def test_empty_database(self, client):
        """Test GET /messages with no messages returns empty list."""
        response = client.get("/messages")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0
    
    def test_get_all_messages(self, seeded_client):
        """Test GET /messages returns all messages with default pagination."""
        response = seeded_client.get("/messages")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 6
        assert data["total"] == 6
        assert data["limit"] == 50
        assert data["offset"] == 0
    
    def test_message_fields(self, seeded_client):
        """Test that message response contains all required fields."""
        response = seeded_client.get("/messages")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check first message has all required fields
        msg = data["data"][0]
        assert "message_id" in msg
        assert "from" in msg  # Should be serialized as 'from'
        assert "to" in msg
        assert "ts" in msg
        # text can be null
    
    def test_ordering_by_timestamp_asc(self, seeded_client):
        """Test messages are ordered by ts ASC, message_id ASC."""
        response = seeded_client.get("/messages")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify ordering
        timestamps = [msg["ts"] for msg in data["data"]]
        assert timestamps == sorted(timestamps)
        
        # First message should be m1 (earliest timestamp)
        assert data["data"][0]["message_id"] == "m1"
        # Last message should be m6 (latest timestamp)
        assert data["data"][5]["message_id"] == "m6"
    
    def test_response_includes_request_id_header(self, seeded_client):
        """Test that response includes X-Request-ID header."""
        response = seeded_client.get("/messages")
        
        assert response.status_code == 200
        assert "x-request-id" in response.headers


class TestMessagesPagination:
    """Test pagination parameters."""
    
    def test_limit_parameter(self, seeded_client):
        """Test limit parameter restricts number of messages."""
        response = seeded_client.get("/messages", params={"limit": 3})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3
        assert data["total"] == 6  # Total count ignores limit
        assert data["limit"] == 3
    
    def test_offset_parameter(self, seeded_client):
        """Test offset parameter skips messages."""
        response = seeded_client.get("/messages", params={"offset": 3})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3  # 6 total - 3 offset = 3 remaining
        assert data["total"] == 6
        assert data["offset"] == 3
        
        # First message should be m4 (4th message after skipping 3)
        assert data["data"][0]["message_id"] == "m4"
    
    def test_limit_and_offset_together(self, seeded_client):
        """Test limit and offset work together for pagination."""
        # Get page 2 with page size 2
        response = seeded_client.get("/messages", params={"limit": 2, "offset": 2})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
        assert data["total"] == 6
        assert data["limit"] == 2
        assert data["offset"] == 2
        
        # Should get messages m3 and m4
        assert data["data"][0]["message_id"] == "m3"
        assert data["data"][1]["message_id"] == "m4"
    
    def test_offset_beyond_total(self, seeded_client):
        """Test offset larger than total returns empty list."""
        response = seeded_client.get("/messages", params={"offset": 100})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 0
        assert data["total"] == 6  # Total is still 6
    
    def test_limit_min_value(self, seeded_client):
        """Test limit minimum value of 1."""
        response = seeded_client.get("/messages", params={"limit": 1})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
    
    def test_limit_max_value(self, seeded_client):
        """Test limit maximum value of 100."""
        response = seeded_client.get("/messages", params={"limit": 100})
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 100
    
    def test_limit_below_min_rejected(self, seeded_client):
        """Test limit below 1 is rejected."""
        response = seeded_client.get("/messages", params={"limit": 0})
        
        assert response.status_code == 422
    
    def test_limit_above_max_rejected(self, seeded_client):
        """Test limit above 100 is rejected."""
        response = seeded_client.get("/messages", params={"limit": 101})
        
        assert response.status_code == 422
    
    def test_negative_offset_rejected(self, seeded_client):
        """Test negative offset is rejected."""
        response = seeded_client.get("/messages", params={"offset": -1})
        
        assert response.status_code == 422


class TestMessagesFilterBySender:
    """Test filtering by sender (from parameter)."""
    
    def test_filter_by_sender(self, seeded_client):
        """Test filtering messages by sender phone number."""
        response = seeded_client.get("/messages", params={"from": "+919876543210"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3  # m1, m2, m6
        assert data["total"] == 3
        
        # All messages should be from the filtered sender
        for msg in data["data"]:
            assert msg["from"] == "+919876543210"
    
    def test_filter_by_different_sender(self, seeded_client):
        """Test filtering by another sender."""
        response = seeded_client.get("/messages", params={"from": "+911234567890"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2  # m3, m4
        assert data["total"] == 2
    
    def test_filter_by_nonexistent_sender(self, seeded_client):
        """Test filtering by sender with no messages returns empty."""
        response = seeded_client.get("/messages", params={"from": "+10000000000"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 0
        assert data["total"] == 0
    
    def test_filter_sender_with_pagination(self, seeded_client):
        """Test sender filter works with pagination."""
        response = seeded_client.get("/messages", params={"from": "+919876543210", "limit": 2})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
        assert data["total"] == 3  # Total matching filter, not limited


class TestMessagesFilterByTimestamp:
    """Test filtering by timestamp (since parameter)."""
    
    def test_filter_by_since(self, seeded_client):
        """Test filtering messages with ts >= since."""
        response = seeded_client.get("/messages", params={"since": "2025-01-15T10:03:00Z"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3  # m4, m5, m6
        assert data["total"] == 3
        
        # All messages should have ts >= since
        for msg in data["data"]:
            assert msg["ts"] >= "2025-01-15T10:03:00Z"
    
    def test_filter_since_exact_match(self, seeded_client):
        """Test since includes messages with exact timestamp match."""
        response = seeded_client.get("/messages", params={"since": "2025-01-15T10:02:00Z"})
        
        assert response.status_code == 200
        data = response.json()
        
        # m3 has ts exactly equal to since, should be included
        message_ids = [msg["message_id"] for msg in data["data"]]
        assert "m3" in message_ids
    
    def test_filter_since_future_timestamp(self, seeded_client):
        """Test since in future returns empty list."""
        response = seeded_client.get("/messages", params={"since": "2030-01-01T00:00:00Z"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 0
        assert data["total"] == 0
    
    def test_filter_since_before_all_messages(self, seeded_client):
        """Test since before all messages returns all."""
        response = seeded_client.get("/messages", params={"since": "2020-01-01T00:00:00Z"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 6
        assert data["total"] == 6


class TestMessagesTextSearch:
    """Test free-text search (q parameter)."""
    
    def test_search_text_case_insensitive(self, seeded_client):
        """Test text search is case-insensitive."""
        # Search lowercase
        response = seeded_client.get("/messages", params={"q": "hello"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2  # m1 "Hello world", m5 "Hello there"
        assert data["total"] == 2
    
    def test_search_text_uppercase(self, seeded_client):
        """Test text search works with uppercase query."""
        response = seeded_client.get("/messages", params={"q": "HELLO"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
    
    def test_search_text_partial_match(self, seeded_client):
        """Test text search matches partial strings."""
        response = seeded_client.get("/messages", params={"q": "orld"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1  # m1 "Hello world"
        assert data["data"][0]["message_id"] == "m1"
    
    def test_search_no_match(self, seeded_client):
        """Test text search with no matches returns empty."""
        response = seeded_client.get("/messages", params={"q": "nonexistent"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 0
        assert data["total"] == 0
    
    def test_search_does_not_match_null_text(self, seeded_client):
        """Test text search doesn't match messages with null text."""
        # m6 has null text, search should not return it
        response = seeded_client.get("/messages", params={"q": "null"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 0


class TestMessagesCombinedFilters:
    """Test combining multiple filters."""
    
    def test_filter_sender_and_since(self, seeded_client):
        """Test combining sender and since filters."""
        response = seeded_client.get("/messages", params={
            "from": "+919876543210",
            "since": "2025-01-15T10:01:00Z"
        })
        
        assert response.status_code == 200
        data = response.json()
        # +919876543210 has m1, m2, m6
        # since 10:01:00Z filters out m1
        # Should return m2 and m6
        assert len(data["data"]) == 2
        assert data["total"] == 2
    
    def test_filter_sender_and_text_search(self, seeded_client):
        """Test combining sender and text search filters."""
        response = seeded_client.get("/messages", params={
            "from": "+919876543210",
            "q": "hello"
        })
        
        assert response.status_code == 200
        data = response.json()
        # Only m1 matches both filters
        assert len(data["data"]) == 1
        assert data["data"][0]["message_id"] == "m1"
    
    def test_filter_since_and_text_search(self, seeded_client):
        """Test combining since and text search filters."""
        response = seeded_client.get("/messages", params={
            "since": "2025-01-15T10:02:00Z",
            "q": "see"
        })
        
        assert response.status_code == 200
        data = response.json()
        # m4 "See you later" matches both
        assert len(data["data"]) == 1
        assert data["data"][0]["message_id"] == "m4"
    
    def test_all_filters_combined(self, seeded_client):
        """Test combining all filters at once."""
        response = seeded_client.get("/messages", params={
            "from": "+911234567890",
            "since": "2025-01-15T10:00:00Z",
            "q": "bye",
            "limit": 10,
            "offset": 0
        })
        
        assert response.status_code == 200
        data = response.json()
        # Only m3 "Goodbye" matches all filters
        assert len(data["data"]) == 1
        assert data["data"][0]["message_id"] == "m3"
    
    def test_filters_with_pagination(self, seeded_client):
        """Test filters work correctly with pagination."""
        # First page
        response1 = seeded_client.get("/messages", params={
            "from": "+919876543210",
            "limit": 2,
            "offset": 0
        })
        
        assert response1.status_code == 200
        data1 = response1.json()
        assert len(data1["data"]) == 2
        assert data1["total"] == 3  # Total matching filter
        
        # Second page
        response2 = seeded_client.get("/messages", params={
            "from": "+919876543210",
            "limit": 2,
            "offset": 2
        })
        
        assert response2.status_code == 200
        data2 = response2.json()
        assert len(data2["data"]) == 1  # Only 1 remaining
        assert data2["total"] == 3
