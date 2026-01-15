"""
Pytest configuration and shared fixtures.

Environment variables are loaded from .env.test via Makefile.
This file ensures settings are reloaded with test env vars before imports.
"""

import pytest

# Clear settings cache before any app imports to ensure test env vars are used
from app.config import get_settings
get_settings.cache_clear()
