"""
Utility functions for the Webhook API.
"""

import hmac
import hashlib
import logging

logger = logging.getLogger(__name__)


def verify_hmac_signature(body: bytes, signature: str, secret: str) -> bool:
    """
    Verify HMAC-SHA256 signature.

    Args:
        body: Raw request body bytes
        signature: Hex-encoded signature from X-Signature header
        secret: WEBHOOK_SECRET

    Returns:
        True if signature is valid, False otherwise
    """
    logger.info("Verifying HMAC signature")
    logger.debug(f"Body length: {len(body)} bytes, signature: {signature[:8]}...")

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    logger.debug(f"Expected signature: {expected_signature[:8]}...")

    # Use constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(expected_signature, signature)
    logger.info(f"HMAC signature verification: {'valid' if is_valid else 'invalid'}")

    return is_valid
