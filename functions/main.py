"""
VoteWise India — standalone Flask backend for Cloud Run.

This module exposes:
    - /chat        (POST)
    - /eligibility (GET)
    - /timeline    (GET)
    - /states      (GET)
    - /health      (GET)

It also serves the frontend from ../static for single-service deployment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, Request, Response, request, send_from_directory

try:
    from .gemini_client import generate_reply
    from .rules_engine import (
        ELECTION_DATA,
        check_eligibility,
        find_local_answer,
        get_deadlines,
        get_state_rules,
    )
except ImportError:
    from gemini_client import generate_reply
    from rules_engine import (
        ELECTION_DATA,
        check_eligibility,
        find_local_answer,
        get_deadlines,
        get_state_rules,
    )

MAX_MESSAGE_LEN: int = 500
_SAFE_CTX_KEYS: frozenset[str] = frozenset({"state", "language", "session_id"})
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    ),
}
_CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "3600",
}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STATIC_DIR = _PROJECT_ROOT / "static"
_PORT = int(os.environ.get("PORT", "8080"))

app = Flask(__name__, static_folder=str(_STATIC_DIR), static_url_path="")


def get_db() -> None:
    """Compatibility helper kept for existing tests."""
    return None


def _response_headers() -> dict[str, str]:
    return {**_SECURITY_HEADERS, **_CORS_HEADERS}


def _json_response(payload: dict[str, Any], status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False),
        status=status,
        headers={**_response_headers(), "Content-Type": "application/json"},
    )


def _empty_response(status: int = 204) -> Response:
    return Response("", status=status, headers=_response_headers())


def _safe_context(raw_ctx: Any) -> dict[str, Any]:
    if not isinstance(raw_ctx, dict):
        return {}
    return {k: str(v)[:100] for k, v in raw_ctx.items() if k in _SAFE_CTX_KEYS}


def pick_followups(reply: str) -> list[str]:
    r = reply.lower()
    if "form 6" in r or "register" in r:
        return ["What documents for Form 6?", "Can I register online?", "Where is my BLO?"]
    if "epic" in r or "voter id" in r:
        return ["How to get e-EPIC?", "How to correct Voter ID?", "Lost my Voter ID?"]
    if "evm" in r or "vvpat" in r:
        return ["Is EVM safe?", "What is VVPAT?", "How to use EVM?"]
    if "unable" in r or "cannot vote" in r:
        return ["How to register now?", "Name not on list?", "What ID do I need?"]
    if "lok sabha" in r:
        return ["What is Vidhan Sabha?", "How many Lok Sabha seats?", "Next general election?"]
    return ["How do I register?", "What is EPIC?", "Find my polling booth?"]


def chat(request_obj: Request) -> Response:
    if request_obj.method == "OPTIONS":
        return _empty_response()
    if request_obj.method != "POST":
        return _json_response({"error": "Method not allowed"}, status=405)

    body = request_obj.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _json_response({"error": "Invalid JSON body"}, status=400)

    message = str(body.get("message", "")).strip()[:MAX_MESSAGE_LEN]
    context = _safe_context(body.get("context", {}))
    if not message:
        return _json_response({"error": "message field is required"}, status=400)

    local_reply = find_local_answer(message)
    if local_reply:
        return _json_response(
            {
                "reply": local_reply,
                "suggested_followups": pick_followups(local_reply),
                "source": "local",
            }
        )

    state = context.get("state", "")
    if state and len(state) == 2 and state.isalpha():
        state = state.upper()
        deadlines = get_deadlines(state)
        rules = get_state_rules(state)
        if "error" not in deadlines:
            context["state_deadlines"] = deadlines
        if "error" not in rules:
            context["state_rules"] = rules

    reply, source = generate_reply(message, context)
    return _json_response(
        {"reply": reply, "suggested_followups": pick_followups(reply), "source": source}
    )


def eligibility(request_obj: Request) -> Response:
    if request_obj.method == "OPTIONS":
        return _empty_response()

    try:
        age = int(request_obj.args.get("age", -1))
        citizen = request_obj.args.get("citizen", "false").lower() == "true"
        state_raw = str(request_obj.args.get("state", "DL"))[:2].upper()
        if not state_raw.isalpha():
            raise ValueError("state must be alphabetic")
        state = state_raw
    except ValueError:
        return _json_response({"error": "Invalid query parameters"}, status=400)

    if not 0 <= age <= 150:
        return _json_response({"error": "age must be between 0 and 150"}, status=422)

    return _json_response(check_eligibility(age, citizen, state), status=200)


def timeline(request_obj: Request) -> Response:
    if request_obj.method == "OPTIONS":
        return _empty_response()

    state = str(request_obj.args.get("state", ""))[:2].upper()
    if len(state) != 2 or not state.isalpha():
        return _json_response({"error": "state must be a 2-letter code (e.g. DL, MH)"}, status=400)

    deadlines = get_deadlines(state)
    if "error" in deadlines:
        return _json_response(deadlines, status=404)
    return _json_response(deadlines, status=200)


def states(request_obj: Request) -> Response:
    if request_obj.method == "OPTIONS":
        return _empty_response()
    return _json_response({"states": list(ELECTION_DATA.get("states", {}).keys())}, status=200)


def health(request_obj: Request) -> Response:
    if request_obj.method == "OPTIONS":
        return _empty_response()
    return _json_response({"status": "ok", "backend": "standalone-cloud-run"}, status=200)


@app.after_request
def add_security_headers(resp: Response) -> Response:
    for key, value in _response_headers().items():
        if key not in resp.headers:
            resp.headers[key] = value
    return resp


@app.route("/chat", methods=["POST", "OPTIONS"])
def chat_route() -> Response:
    return chat(request)


@app.route("/eligibility", methods=["GET", "OPTIONS"])
def eligibility_route() -> Response:
    return eligibility(request)


@app.route("/timeline", methods=["GET", "OPTIONS"])
def timeline_route() -> Response:
    return timeline(request)


@app.route("/states", methods=["GET", "OPTIONS"])
def states_route() -> Response:
    return states(request)


@app.route("/health", methods=["GET", "OPTIONS"])
def health_route() -> Response:
    return health(request)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path: str) -> Response:
    if path:
        target = (_STATIC_DIR / path).resolve()
        static_root = _STATIC_DIR.resolve()
        if str(target).startswith(str(static_root)) and target.is_file():
            return send_from_directory(str(_STATIC_DIR), path)
    return send_from_directory(str(_STATIC_DIR), "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=_PORT)
