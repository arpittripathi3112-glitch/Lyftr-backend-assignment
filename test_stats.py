"""
Tests for the GET /stats endpoint.

Tests cover:
- Empty database returns zeros/nulls
- Total messages count
- Unique senders count
- Top 10 senders by message count
- First and last message timestamps
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
    # Create test messages with different senders and timestamps
    # Sender +919876543210: 3 messages (m1, m2, m6)
    # Sender +911234567890: 2 messages (m3, m4)
    # Sender +919999999999: 1 message (m5)
    messages = [
        ("m1", "+919876543210", "+14155550100", "2025-01-15T10:00:00Z", "Hello world"),
        ("m2", "+919876543210", "+14155550100", "2025-01-15T10:01:00Z", "How are you?"),
        ("m3", "+911234567890", "+14155550100", "2025-01-15T10:02:00Z", "Goodbye"),
        ("m4", "+911234567890", "+14155550100", "2025-01-15T10:03:00Z", "See you later"),
        ("m5", "+919999999999", "+14155550100", "2025-01-15T10:04:00Z", "Hello there"),
        ("m6", "+919876543210", "+14155550100", "2025-01-15T10:05:00Z", None),
    ]
    
    for msg in messages:
        create_message(client, *msg)
    
    return client


class TestStatsEmpty:
    """Test stats endpoint with empty database."""
    
    def test_empty_database_stats(self, client):
        """Test GET /stats with no messages returns zeros and nulls."""
        response = client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_messages"] == 0
        assert data["senders_count"] == 0
        assert data["messages_per_sender"] == []
        assert data["first_message_ts"] is None
        assert data["last_message_ts"] is None
    
    def test_stats_response_includes_request_id_header(self, client):
        """Test that response includes X-Request-ID header."""
        response = client.get("/stats")
        
        assert response.status_code == 200
        assert "x-request-id" in response.headers


class TestStatsTotalMessages:
    """Test total_messages field."""
    
    def test_total_messages_count(self, seeded_client):
        """Test total_messages equals total number of messages."""
        response = seeded_client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_messages"] == 6
    
    def test_total_messages_after_adding_one(self, client):
        """Test total_messages increments after adding a message."""
        # Initially empty
        response = client.get("/stats")
        assert response.json()["total_messages"] == 0
        
        # Add one message
        create_message(client, "m1", "+919876543210", "+14155550100", "2025-01-15T10:00:00Z", "Hello")
        
        response = client.get("/stats")
        assert response.json()["total_messages"] == 1


class TestStatsSendersCount:
    """Test senders_count field."""
    
    def test_senders_count(self, seeded_client):
        """Test senders_count equals number of unique senders."""
        response = seeded_client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        # We have 3 unique senders: +919876543210, +911234567890, +919999999999
        assert data["senders_count"] == 3
    
    def test_senders_count_single_sender(self, client):
        """Test senders_count with messages from same sender."""
        # Add 3 messages from same sender
        create_message(client, "m1", "+919876543210", "+14155550100", "2025-01-15T10:00:00Z", "Hello")
        create_message(client, "m2", "+919876543210", "+14155550100", "2025-01-15T10:01:00Z", "World")
        create_message(client, "m3", "+919876543210", "+14155550100", "2025-01-15T10:02:00Z", "Test")
        
        response = client.get("/stats")
        data = response.json()
        assert data["senders_count"] == 1
        assert data["total_messages"] == 3


class TestStatsMessagesPerSender:
    """Test messages_per_sender field."""
    
    def test_messages_per_sender_sorted_by_count_desc(self, seeded_client):
        """Test messages_per_sender is sorted by count descending."""
        response = seeded_client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        senders = data["messages_per_sender"]
        assert len(senders) == 3
        
        # Should be sorted by count descending
        # +919876543210: 3, +911234567890: 2, +919999999999: 1
        assert senders[0]["from"] == "+919876543210"
        assert senders[0]["count"] == 3
        
        assert senders[1]["from"] == "+911234567890"
        assert senders[1]["count"] == 2
        
        assert senders[2]["from"] == "+919999999999"
        assert senders[2]["count"] == 1
    
    def test_messages_per_sender_top_10_limit(self, client):
        """Test messages_per_sender returns at most 10 senders."""
        # Create messages from 12 different senders
        for i in range(12):
            sender = f"+9100000000{i:02d}"
            create_message(client, f"m{i}", sender, "+14155550100", f"2025-01-15T10:{i:02d}:00Z", f"Message {i}")
        
        response = client.get("/stats")
        data = response.json()
        
        assert data["total_messages"] == 12
        assert data["senders_count"] == 12
        # But only top 10 in messages_per_sender
        assert len(data["messages_per_sender"]) == 10
    
    def test_messages_per_sender_counts_sum(self, seeded_client):
        """Test that sum of counts for listed senders equals their contribution."""
        response = seeded_client.get("/stats")
        data = response.json()
        
        # Sum of all sender counts should equal total (when all senders fit in top 10)
        total_from_senders = sum(s["count"] for s in data["messages_per_sender"])
        assert total_from_senders == data["total_messages"]


class TestStatsTimestamps:
    """Test first_message_ts and last_message_ts fields."""
    
    def test_first_and_last_timestamps(self, seeded_client):
        """Test first and last message timestamps are correct."""
        response = seeded_client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        # First message: m1 at 2025-01-15T10:00:00Z
        assert data["first_message_ts"] == "2025-01-15T10:00:00Z"
        # Last message: m6 at 2025-01-15T10:05:00Z
        assert data["last_message_ts"] == "2025-01-15T10:05:00Z"
    
    def test_single_message_same_first_and_last(self, client):
        """Test with single message, first and last are the same."""
        create_message(client, "m1", "+919876543210", "+14155550100", "2025-01-15T10:00:00Z", "Hello")
        
        response = client.get("/stats")
        data = response.json()
        
        assert data["first_message_ts"] == "2025-01-15T10:00:00Z"
        assert data["last_message_ts"] == "2025-01-15T10:00:00Z"
    
    def test_timestamps_null_when_empty(self, client):
        """Test timestamps are null when no messages exist."""
        response = client.get("/stats")
        data = response.json()
        
        assert data["first_message_ts"] is None
        assert data["last_message_ts"] is None


class TestStatsResponseStructure:
    """Test stats response structure and fields."""
    
    def test_response_has_all_required_fields(self, seeded_client):
        """Test response contains all required fields."""
        response = seeded_client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "total_messages" in data
        assert "senders_count" in data
        assert "messages_per_sender" in data
        assert "first_message_ts" in data
        assert "last_message_ts" in data
    
    def test_messages_per_sender_entry_structure(self, seeded_client):
        """Test each entry in messages_per_sender has from and count."""
        response = seeded_client.get("/stats")
        data = response.json()
        
        for entry in data["messages_per_sender"]:
            assert "from" in entry
            assert "count" in entry
            assert isinstance(entry["from"], str)
            assert isinstance(entry["count"], int)
            assert entry["count"] > 0
