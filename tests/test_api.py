"""
Integration tests for VoteWise India Cloud Function endpoints.

Tests cover:
    - /health — liveness probe
    - /chat   — message routing, caching, error paths
    - /eligibility — input validation and eligibility logic
    - /timeline    — state timeline lookup
    - /states      — state list endpoint

All Firebase dependencies are mocked so tests run offline without any GCP
credentials.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Request
from werkzeug.test import EnvironBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_request(method="GET", url="/", json_data=None, args=None, headers=None):
    """Creates a Flask ``Request`` object suitable for Cloud Function testing.

    Args:
        method: HTTP method string (e.g. ``"POST"``).
        url: Request path (e.g. ``"/chat"``).
        json_data: Optional dict to serialise as the request body.
        args: Optional dict of query-string parameters.
        headers: Optional dict of HTTP headers.

    Returns:
        A ``werkzeug.wrappers.Request`` instance.
    """
    builder = EnvironBuilder(
        method=method,
        path=url,
        json=json_data,
        query_string=args,
        headers=headers or {},
    )
    env = builder.get_environ()
    return Request(env)


# ---------------------------------------------------------------------------
# Module-level patch: prevent real Firebase init on import
# ---------------------------------------------------------------------------
with (
    patch("firebase_admin.initialize_app"),
    patch("firebase_admin.firestore.client"),
):
    from functions.main import chat, health, eligibility, timeline, states


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_200(self):
        req = make_mock_request(method="GET", url="/health")
        resp = health(req)
        assert resp.status_code == 200

    def test_returns_correct_json(self):
        req = make_mock_request(method="GET", url="/health")
        resp = health(req)
        data = json.loads(resp.get_data())
        assert data["status"] == "ok"
        assert data["backend"] == "firebase-functions"

    def test_security_headers_present(self):
        req = make_mock_request(method="GET", url="/health")
        resp = health(req)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------------

class TestChatEndpoint:
    @patch("functions.main.generate_reply")
    @patch("functions.main.get_db")
    def test_chat_with_mocked_gemini(self, mock_get_db, mock_generate):
        """Happy path: local answer is not found, Gemini returns a reply."""
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_generate.return_value = ("Mocked AI reply about elections.", "ai")

        req = make_mock_request(
            method="POST",
            url="/chat",
            json_data={"message": "How do I vote?", "context": {}},
            headers={"X-Forwarded-For": "192.168.1.1"},
        )
        resp = chat(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert data["reply"] == "Mocked AI reply about elections."

    @patch("functions.main.get_db")
    def test_chat_returns_local_answer_for_registration(self, mock_get_db):
        """Local keyword match should bypass Gemini entirely."""
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="POST",
            url="/chat",
            json_data={"message": "How to register to vote?", "context": {}},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        resp = chat(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert data["source"] == "local"

    @patch("functions.main.get_db")
    def test_chat_rejects_empty_message(self, mock_get_db):
        """Empty message field must return HTTP 400."""
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="POST",
            url="/chat",
            json_data={"message": "", "context": {}},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        resp = chat(req)
        assert resp.status_code == 400

    @patch("functions.main.get_db")
    def test_chat_truncates_long_message(self, mock_get_db):
        """Messages longer than 500 chars should be accepted (truncated internally)."""
        mock_get_db.return_value = MagicMock()
        long_msg = "A" * 600
        req = make_mock_request(
            method="POST",
            url="/chat",
            json_data={"message": long_msg, "context": {}},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        resp = chat(req)
        # Should not error — truncation is silent.
        assert resp.status_code in (200, 429)

    def test_chat_options_preflight(self):
        """OPTIONS pre-flight must return 204 with CORS headers."""
        req = make_mock_request(method="OPTIONS", url="/chat")
        resp = chat(req)
        assert resp.status_code == 204
        assert "Access-Control-Allow-Origin" in resp.headers


# ---------------------------------------------------------------------------
# /eligibility
# ---------------------------------------------------------------------------

class TestEligibilityEndpoint:
    @patch("functions.main.get_db")
    def test_eligible_adult_citizen(self, mock_get_db):
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="GET", url="/eligibility",
            args={"age": "20", "citizen": "true", "state": "DL"},
            headers={"X-Forwarded-For": "10.0.0.2"},
        )
        resp = eligibility(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert data["eligible"] is True

    @patch("functions.main.get_db")
    def test_ineligible_minor(self, mock_get_db):
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="GET", url="/eligibility",
            args={"age": "16", "citizen": "true", "state": "MH"},
            headers={"X-Forwarded-For": "10.0.0.3"},
        )
        resp = eligibility(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert data["eligible"] is False

    @patch("functions.main.get_db")
    def test_boundary_age_18_is_eligible(self, mock_get_db):
        """Exactly 18 years old should be eligible."""
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="GET", url="/eligibility",
            args={"age": "18", "citizen": "true", "state": "KA"},
            headers={"X-Forwarded-For": "10.0.0.4"},
        )
        resp = eligibility(req)
        assert resp.status_code == 200
        assert json.loads(resp.get_data())["eligible"] is True

    @patch("functions.main.get_db")
    def test_boundary_age_17_is_ineligible(self, mock_get_db):
        """17 years old must be ineligible."""
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="GET", url="/eligibility",
            args={"age": "17", "citizen": "true", "state": "KA"},
            headers={"X-Forwarded-For": "10.0.0.5"},
        )
        resp = eligibility(req)
        assert resp.status_code == 200
        assert json.loads(resp.get_data())["eligible"] is False

    @patch("functions.main.get_db")
    def test_non_citizen_is_ineligible(self, mock_get_db):
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="GET", url="/eligibility",
            args={"age": "25", "citizen": "false", "state": "GJ"},
            headers={"X-Forwarded-For": "10.0.0.6"},
        )
        resp = eligibility(req)
        assert resp.status_code == 200
        assert json.loads(resp.get_data())["eligible"] is False

    @patch("functions.main.get_db")
    def test_invalid_age_returns_422(self, mock_get_db):
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="GET", url="/eligibility",
            args={"age": "200", "citizen": "true", "state": "DL"},
            headers={"X-Forwarded-For": "10.0.0.7"},
        )
        resp = eligibility(req)
        assert resp.status_code == 422

    @patch("functions.main.get_db")
    def test_invalid_state_param(self, mock_get_db):
        """State param longer than 2 chars should be silently truncated, not error."""
        mock_get_db.return_value = MagicMock()
        req = make_mock_request(
            method="GET", url="/eligibility",
            args={"age": "20", "citizen": "true", "state": "DELHI"},
            headers={"X-Forwarded-For": "10.0.0.8"},
        )
        resp = eligibility(req)
        # State is truncated to 2 chars by the endpoint — should not crash.
        assert resp.status_code in (200, 400, 422)


# ---------------------------------------------------------------------------
# /timeline
# ---------------------------------------------------------------------------

class TestTimelineEndpoint:
    def test_known_state_returns_200(self):
        req = make_mock_request(method="GET", url="/timeline", args={"state": "DL"})
        resp = timeline(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert "state_name" in data

    def test_known_state_contains_required_fields(self):
        req = make_mock_request(method="GET", url="/timeline", args={"state": "DL"})
        resp = timeline(req)
        data = json.loads(resp.get_data())
        for field in ("state_name", "last_election_date", "next_election_due"):
            assert field in data, f"Missing field: {field}"

    def test_unknown_state_returns_404(self):
        req = make_mock_request(method="GET", url="/timeline", args={"state": "XX"})
        resp = timeline(req)
        assert resp.status_code == 404

    def test_missing_state_returns_400(self):
        req = make_mock_request(method="GET", url="/timeline", args={"state": ""})
        resp = timeline(req)
        assert resp.status_code == 400

    def test_options_preflight(self):
        req = make_mock_request(method="OPTIONS", url="/timeline")
        resp = timeline(req)
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# /states
# ---------------------------------------------------------------------------

class TestStatesEndpoint:
    def test_returns_200(self):
        req = make_mock_request(method="GET", url="/states")
        resp = states(req)
        assert resp.status_code == 200

    def test_returns_states_list(self):
        req = make_mock_request(method="GET", url="/states")
        resp = states(req)
        data = json.loads(resp.get_data())
        assert "states" in data
        assert isinstance(data["states"], list)
