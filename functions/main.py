"""
VoteWise India — Firebase Cloud Functions (Gen 2).

Provides HTTPS-triggered Cloud Functions for the VoteWise India election
assistant. All endpoints enforce CORS, rate limiting via Firestore, and
optional Firebase App Check / Auth token verification.

Endpoints:
    /chat       — Primary AI chat endpoint (POST)
    /eligibility — Voter eligibility checker (GET)
    /timeline   — State election timeline (GET)
    /states     — List supported state codes (GET)
    /health     — Health probe (GET)
"""

import json
import logging
import os
import time
from typing import Optional

import firebase_admin
from firebase_admin import auth, firestore, app_check
from firebase_functions import https_fn, options

# Local modules (same package)
from rules_engine import (
    check_eligibility, get_deadlines, get_state_rules,
    find_local_answer, ELECTION_DATA,
)
from gemini_client import generate_reply

# ── Firebase Admin init (singleton) ──────────────────────────────────────────
if not firebase_admin._apps:
    firebase_admin.initialize_app()

_db: Optional[firestore.client] = None


def get_db() -> firestore.client:
    """Returns a lazily-initialised Firestore client (singleton).

    Returns:
        A Firestore client instance shared across all function invocations
        in the same container.
    """
    global _db
    if _db is None:
        _db = firestore.client()
    return _db


# ── Constants ────────────────────────────────────────────────────────────────
# Maximum allowed message length to prevent prompt-injection and quota abuse.
MAX_MESSAGE_LEN: int = 500
# Maximum number of keys allowed in the context dictionary per request.
MAX_CONTEXT_KEYS: int = 10
# Maximum API requests per hour per anonymous or authenticated user.
RATE_LIMIT: int = 30
# Set to True once reCAPTCHA App Check is configured in the Firebase console.
ENFORCE_APP_CHECK: bool = True
# Supported deployment region — Mumbai, closest to India.
REGION = options.SupportedRegion.ASIA_SOUTH1
# Known-safe context keys accepted from client requests (allowlist).
_SAFE_CTX_KEYS: frozenset = frozenset({"state", "language", "session_id"})
# Valid 2-letter Indian state / UT codes.
_VALID_STATE_CODES: frozenset = frozenset({
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN",
    "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD",
    "MH", "ML", "MN", "MP", "MZ", "NL", "OR", "PB", "PY", "RJ",
    "SK", "TG", "TN", "TR", "UP", "UT", "WB",
})

# ── CORS — restricted to production domains only ─────────────────────────────
_ALLOWED_ORIGINS: frozenset = frozenset({
    "https://voterwise-c0186.web.app",
    "https://voterwise-c0186.firebaseapp.com",
})
_DEFAULT_ORIGIN: str = "https://voterwise-c0186.web.app"

# Security response headers added to every response.
_SECURITY_HEADERS: dict = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # CSP: allow resources only from same origin and trusted CDNs used by the app.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://www.gstatic.com; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self' https://*.googleapis.com https://*.firebaseio.com; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    ),
}

# Public CORS header used for endpoints that serve no sensitive user data.
CORS_HEADERS: dict = {
    "Access-Control-Allow-Origin": "*",
    "Vary": "Origin",
    **_SECURITY_HEADERS,
}


def _cors(request: https_fn.Request) -> dict:
    """Returns CORS headers, reflecting origin only if it is in the allowlist.

    Args:
        request: The incoming HTTPS Cloud Function request.

    Returns:
        A dict of CORS and security headers safe to merge into any response.
    """
    origin = request.headers.get("Origin", "")
    allowed = origin if origin in _ALLOWED_ORIGINS else _DEFAULT_ORIGIN
    return {
        "Access-Control-Allow-Origin": allowed,
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Firebase-AppCheck",
        "Access-Control-Max-Age": "3600",
        "Vary": "Origin",
        **_SECURITY_HEADERS,
    }


# ── Auth + Rate Limiting ──────────────────────────────────────────────────────

def _verify_and_rate_limit(
    request: https_fn.Request,
) -> tuple[Optional[str], Optional[https_fn.Response]]:
    """Verifies Firebase App Check, ID token, and applies per-user rate limiting.

    Performs three sequential checks:
        1. Firebase App Check (if ENFORCE_APP_CHECK is True).
        2. Bearer token verification via Firebase Auth (optional — falls through
           to IP-based anonymous session if token is absent or invalid).
        3. Sliding-window rate limit (RATE_LIMIT requests per hour) stored in
           Firestore under the ``rate_limits`` collection.

    IP extraction always uses the last address in ``X-Forwarded-For`` because
    Cloud Run appends the real client IP at the tail, preventing spoofing.

    Args:
        request: The incoming HTTPS Cloud Function request.

    Returns:
        A tuple ``(uid, None)`` on success, or ``(None, error_response)`` when
        App Check validation fails or the rate limit is exceeded.
    """
    import hashlib

    # ── 1. App Check Verification ─────────────────────────────────────────────
    if ENFORCE_APP_CHECK:
        app_check_token = request.headers.get("X-Firebase-AppCheck", "")
        if not app_check_token:
            return None, https_fn.Response(
                json.dumps({"error": "Unauthorized: Missing App Check token."}),
                status=401,
                headers={**CORS_HEADERS, "Content-Type": "application/json"},
            )
        try:
            app_check.verify_token(app_check_token)
        except Exception as exc:
            logging.warning("App Check verification failed: %s", exc)
            return None, https_fn.Response(
                json.dumps({"error": "Unauthorized: Invalid App Check token."}),
                status=401,
                headers={**CORS_HEADERS, "Content-Type": "application/json"},
            )

    # ── 2. User Auth / IP Rate Limiting ──────────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    uid: Optional[str] = None

    if auth_header.startswith("Bearer "):
        id_token = auth_header.split("Bearer ")[1].strip()
        try:
            decoded = auth.verify_id_token(id_token)
            uid = decoded["uid"]
        except Exception as exc:
            logging.warning("Token verification failed: %s", exc)
            # Fall through to IP-based rate limiting

    if not uid:
        # Always use the LAST IP in X-Forwarded-For — Cloud Run appends the
        # real client IP at the end, which callers cannot spoof.
        forwarded = request.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[-1].strip() if forwarded else (request.remote_addr or "unknown")
        uid = "anon-" + hashlib.sha256(ip.encode()).hexdigest()[:16]

    # ── 3. Rate limiting via Firestore transaction ────────────────────────────
    db = get_db()
    ref = db.collection("rate_limits").document(uid)

    @firestore.transactional
    def _check_limit(transaction) -> bool:
        """Atomically reads and increments the rate-limit counter.

        Args:
            transaction: The active Firestore transaction.

        Returns:
            True if the request is within the rate limit, False otherwise.
        """
        snap = ref.get(transaction=transaction)
        now = time.time()
        if snap.exists:
            data = snap.to_dict()
            window_start: float = data.get("window_start", 0)
            count: int = data.get("count", 0)
            if now - window_start < 3600:
                if count >= RATE_LIMIT:
                    return False
                transaction.update(ref, {"count": count + 1})
                return True
        transaction.set(ref, {"window_start": now, "count": 1})
        return True

    try:
        allowed = _check_limit(db.transaction())
    except Exception as exc:
        logging.warning("Rate limit check error: %s", exc)
        allowed = True  # Fail open — never block real users on DB errors.

    if not allowed:
        return None, https_fn.Response(
            json.dumps({"error": "Rate limit exceeded. Try again in an hour."}),
            status=429,
            headers={**CORS_HEADERS, "Content-Type": "application/json"},
        )

    return uid, None


# ── Analytics writer ─────────────────────────────────────────────────────────

def _log_chat(
    uid: str,
    message: str,
    source: str,
    state: Optional[str],
    language: str,
    response_time_ms: int,
) -> None:
    """Writes a single chat interaction to the Firestore analytics subcollection.

    Failures are silently swallowed so analytics never block a user response.

    Args:
        uid: The Firebase UID or anonymous IP-hash identifying the session.
        message: The user's sanitised message text.
        source: One of ``"local"``, ``"cache"``, or ``"ai"``.
        state: The 2-letter Indian state code, or ``None`` if not selected.
        language: The UI language name (e.g. ``"Hindi"``).
        response_time_ms: End-to-end latency in milliseconds for this request.
    """
    try:
        db = get_db()
        db.collection("analytics").document("chats").collection("entries").add({
            "session_id": uid,
            "message": message,
            "reply_source": source,
            "state": state,
            "language": language,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "response_time_ms": response_time_ms,
        })
    except Exception as exc:
        logging.warning("Analytics write error: %s", exc)


# ── Follow-up chips ───────────────────────────────────────────────────────────

def pick_followups(reply: str) -> list[str]:
    """Selects contextually relevant follow-up question chips for a given reply.

    Scans the reply text for known topic keywords and returns up to three
    suggested follow-up questions that the user is likely to ask next.

    Args:
        reply: The bot's reply text (plain text or Markdown).

    Returns:
        A list of exactly three follow-up question strings.
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
# CLOUD FUNCTION: /chat
# ═══════════════════════════════════════════════════════════════════════════════

@https_fn.on_request(region=REGION, memory=options.MemoryOption.MB_512, timeout_sec=120)
def chat(request: https_fn.Request) -> https_fn.Response:
    """Primary AI chat endpoint for VoteWise India.

    Accepts a POST request with a JSON body containing ``message`` and optional
    ``context`` fields, then routes through a 3-layer response pipeline:
        1. Local keyword match (zero API cost, instant).
        2. Rules engine state-data enrichment.
        3. Vertex AI Gemini call (with Firestore caching).

    Args:
        request: The incoming HTTPS Cloud Function request.

    Returns:
        A JSON response containing ``reply``, ``suggested_followups``, and
        ``source`` on success, or an error JSON with an appropriate HTTP status.
    """
    cors = _cors(request)
    if request.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=cors)

    uid, err = _verify_and_rate_limit(request)
    if err:
        return err

    try:
        body = request.get_json(silent=True) or {}
        # Enforce message length limit to prevent prompt injection & quota abuse.
        message = str(body.get("message", "")).strip()[:MAX_MESSAGE_LEN]
        # Sanitize context: accept only whitelisted string keys, bounded size.
        raw_ctx = body.get("context", {})
        if not isinstance(raw_ctx, dict):
            raw_ctx = {}
        context: dict = {
            k: str(v)[:100]            # Cap each value at 100 characters.
            for k, v in raw_ctx.items()
            if k in _SAFE_CTX_KEYS     # Whitelist known keys only.
        }
    except Exception:
        return https_fn.Response(
            json.dumps({"error": "Invalid JSON body"}),
            status=400,
            headers={**cors, "Content-Type": "application/json"},
        )

    if not message:
        return https_fn.Response(
            json.dumps({"error": "message field is required"}),
            status=400,
            headers={**cors, "Content-Type": "application/json"},
        )

    t0 = time.time()

    # Layer 1: local keyword answer — zero cost, instant.
    local_reply = find_local_answer(message)
    if local_reply:
        followups = pick_followups(local_reply)
        _log_chat(
            uid, message, "local",
            context.get("state"), context.get("language", "English"),
            int((time.time() - t0) * 1000),
        )
        return https_fn.Response(
            json.dumps({"reply": local_reply, "suggested_followups": followups, "source": "local"}),
            status=200,
            headers={**cors, "Content-Type": "application/json"},
        )

    # Layer 2: rules engine enrichment — add validated state data to context.
    state = context.get("state", "")
    if state and isinstance(state, str) and len(state) == 2 and state.isalpha():
        state = state.upper()
        deadlines = get_deadlines(state)
        rules = get_state_rules(state)
        if "error" not in deadlines:
            context["state_deadlines"] = deadlines
        if "error" not in rules:
            context["state_rules"] = rules

    # Layer 3: Vertex AI Gemini (with Firestore response cache).
    reply, source = generate_reply(message, context)
    followups = pick_followups(reply)

    _log_chat(
        uid, message, source, state,
        context.get("language", "English"),
        int((time.time() - t0) * 1000),
    )

    return https_fn.Response(
        json.dumps({"reply": reply, "suggested_followups": followups, "source": source}),
        status=200,
        headers={**cors, "Content-Type": "application/json"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLOUD FUNCTION: /eligibility
# ═══════════════════════════════════════════════════════════════════════════════

@https_fn.on_request(region=REGION, memory=options.MemoryOption.MB_512, timeout_sec=30)
def eligibility(request: https_fn.Request) -> https_fn.Response:
    """Voter eligibility checker for Indian elections.

    Accepts a GET request with ``age``, ``citizen``, and ``state`` query
    parameters, then evaluates basic voter eligibility criteria defined under
    the Representation of the People Act, 1951.

    Args:
        request: The incoming HTTPS Cloud Function request with query params:
            - age (int): The voter's age in years.
            - citizen (bool): ``"true"`` if the user claims Indian citizenship.
            - state (str): A 2-letter Indian state/UT code (e.g. ``"DL"``).

    Returns:
        A JSON response containing ``eligible`` (bool), ``reasons`` (list),
        and ``next_steps`` (list), or an error JSON with an HTTP 400/422 status.
    """
    cors = _cors(request)
    if request.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=cors)

    uid, err = _verify_and_rate_limit(request)
    if err:
        return err

    try:
        age = int(request.args.get("age", -1))
        citizen = request.args.get("citizen", "false").lower() == "true"
        state_raw = str(request.args.get("state", "DL"))[:2].upper()
        if not state_raw.isalpha():
            raise ValueError("state must be alphabetic")
        state = state_raw
    except ValueError:
        return https_fn.Response(
            json.dumps({"error": "Invalid query parameters"}),
            status=400,
            headers={**cors, "Content-Type": "application/json"},
        )

    if not 0 <= age <= 150:
        return https_fn.Response(
            json.dumps({"error": "age must be between 0 and 150"}),
            status=422,
            headers={**cors, "Content-Type": "application/json"},
        )

    result = check_eligibility(age, citizen, state)
    return https_fn.Response(
        json.dumps(result),
        status=200,
        headers={**cors, "Content-Type": "application/json"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLOUD FUNCTION: /timeline
# ═══════════════════════════════════════════════════════════════════════════════

@https_fn.on_request(region=REGION, memory=options.MemoryOption.MB_512, timeout_sec=30)
def timeline(request: https_fn.Request) -> https_fn.Response:
    """Returns the election timeline for a given Indian state or UT.

    Accepts a GET request with a ``state`` query parameter (2-letter code) and
    returns key election dates including the last and next election dates, voter
    registration deadlines, and state-specific notes.

    Args:
        request: The incoming HTTPS Cloud Function request with query params:
            - state (str): A 2-letter Indian state/UT code (e.g. ``"MH"``).

    Returns:
        A JSON response with election timeline data on success (HTTP 200), or
        an error JSON with HTTP 400 (invalid code) or 404 (unknown state).
    """
    cors = _cors(request)
    if request.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=cors)

    state = str(request.args.get("state", ""))[:2].upper()
    if len(state) != 2 or not state.isalpha():
        return https_fn.Response(
            json.dumps({"error": "state must be a 2-letter code (e.g. DL, MH)"}),
            status=400,
            headers={**cors, "Content-Type": "application/json"},
        )

    deadlines = get_deadlines(state)
    if "error" in deadlines:
        return https_fn.Response(
            json.dumps(deadlines),
            status=404,
            headers={**cors, "Content-Type": "application/json"},
        )
    return https_fn.Response(
        json.dumps(deadlines),
        status=200,
        headers={**cors, "Content-Type": "application/json"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLOUD FUNCTION: /states
# ═══════════════════════════════════════════════════════════════════════════════

@https_fn.on_request(region=REGION, memory=options.MemoryOption.MB_512, timeout_sec=10)
def states(request: https_fn.Request) -> https_fn.Response:
    """Lists all Indian state/UT codes supported by VoteWise India.

    Public endpoint — no authentication required. Returns the list of 2-letter
    state codes for which election data is available.

    Args:
        request: The incoming HTTPS Cloud Function request.

    Returns:
        A JSON response containing a ``states`` list of 2-letter code strings.
    """
    if request.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=CORS_HEADERS)
    state_list = list(ELECTION_DATA.get("states", {}).keys())
    return https_fn.Response(
        json.dumps({"states": state_list}),
        status=200,
        headers={**CORS_HEADERS, "Content-Type": "application/json"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLOUD FUNCTION: /health
# ═══════════════════════════════════════════════════════════════════════════════

@https_fn.on_request(region=REGION, memory=options.MemoryOption.MB_512, timeout_sec=10)
def health(request: https_fn.Request) -> https_fn.Response:
    """Health probe for the VoteWise India backend.

    Public endpoint — no authentication required. Used by uptime monitors and
    Firebase Hosting rewrites to verify the backend is operational.

    Args:
        request: The incoming HTTPS Cloud Function request.

    Returns:
        A JSON response ``{"status": "ok", "backend": "firebase-functions"}``
        with HTTP 200.
    """
    return https_fn.Response(
        json.dumps({"status": "ok", "backend": "firebase-functions"}),
        status=200,
        headers={**CORS_HEADERS, "Content-Type": "application/json"},
    )
