"""Shared pytest fixtures for the VoteWise India test suite.

This conftest.py is discovered automatically by pytest and provides
reusable fixtures across test_api.py, test_rules.py, and test_safety.py.

Example:
    Run the full test suite::

        pytest tests/ -v --tb=short
"""
from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# App client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    """Return a configured Flask test app with Firebase mocked out.

    Scope is 'session' so Firebase is initialised only once per test run,
    matching the singleton pattern used in production code.

    Yields:
        flask.Flask: The application instance under test.
    """
    with patch("firebase_admin.initialize_app"), \
         patch("firebase_admin.firestore.client", return_value=MagicMock()):
        from functions.main import app as flask_app
        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture()
def client(app):
    """Return a Flask test client for making HTTP requests.

    Args:
        app: The Flask app fixture (injected by pytest).

    Returns:
        flask.testing.FlaskClient: Ready-to-use test client.
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# Firestore mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_db():
    """Return a MagicMock that mimics the Firestore client interface.

    Provides pre-configured return values for the common
    collection → document → get / set / update chain.

    Returns:
        unittest.mock.MagicMock: Mock Firestore client.
    """
    db = MagicMock()
    doc_snapshot = MagicMock()
    doc_snapshot.exists = False
    doc_ref = MagicMock()
    doc_ref.get.return_value = doc_snapshot
    db.collection.return_value.document.return_value = doc_ref
    return db


# ---------------------------------------------------------------------------
# Sample request payload fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def basic_chat_payload() -> dict:
    """Return a minimal valid /chat request payload.

    Returns:
        dict: JSON-serialisable request body.
    """
    return {
        "message": "How do I register to vote?",
        "state": "DL",
        "language": "English",
        "history": [],
    }


@pytest.fixture()
def long_message_payload() -> dict:
    """Return a /chat payload whose message exceeds the 500-char server limit.

    Returns:
        dict: JSON-serialisable request body with an oversized message.
    """
    return {
        "message": "x" * 501,
        "state": "MH",
        "language": "English",
        "history": [],
    }


@pytest.fixture()
def partisan_payload() -> dict:
    """Return a /chat payload containing a partisan keyword that must be refused.

    Returns:
        dict: JSON-serialisable request body with forbidden content.
    """
    return {
        "message": "Which party should I vote for BJP or Congress?",
        "state": "UP",
        "language": "English",
        "history": [],
    }
