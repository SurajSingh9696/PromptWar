"""
VoteWise India — Vertex AI Gemini client with Firestore caching.

Handles all AI-related logic for VoteWise India:
    - Partisan-question refusal guard
    - 24-hour Firestore response cache to minimise Vertex AI costs
    - Primary / fallback model invocation via Vertex AI SDK
    - Graceful degradation with an ECI-sourced offline message

Usage::

    from gemini_client import generate_reply
    reply, source = generate_reply(user_message, grounded_context)
"""

import hashlib
import logging
import os
import time
from typing import Optional

# Lazy imports for vertexai to avoid deployment timeouts
from google.cloud import firestore as firestore_client

from prompts import build_chat_prompt, REFUSAL_TEMPLATES

# ── Vertex AI init (lazy — called on first request) ───────────────────────────
PROJECT_ID: Optional[str] = os.environ.get("GCLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
REGION: str = os.environ.get("VERTEX_REGION", "asia-south1")
_vertex_initialized: bool = False


def _ensure_vertex_init() -> None:
    """Initialises Vertex AI SDK exactly once per container instance.

    Uses a module-level flag so repeated calls are no-ops after the first
    successful initialisation.
    """
    global _vertex_initialized
    if not _vertex_initialized:
        import vertexai
        vertexai.init(project=PROJECT_ID, location=REGION)
        _vertex_initialized = True


# ── Model selection (overridable via environment variables) ───────────────────
# Primary model: cost-efficient flash variant for most queries.
PRIMARY_MODEL: str = os.environ.get("ACTIVE_MODEL", "gemini-1.5-flash")
# Fallback model: used automatically if PRIMARY_MODEL fails.
FALLBACK_MODEL: str = os.environ.get("FALLBACK_MODEL", "gemini-1.5-pro")

# ── Firestore cache settings ──────────────────────────────────────────────────
# Cache lifetime: 24 hours in seconds.
CACHE_TTL_SECONDS: int = 60 * 60 * 24

# ── Generation config ─────────────────────────────────────────────────────────
# Temperature kept low for factual accuracy on civic/legal topics.
_TEMPERATURE: float = 0.2
# Token cap per response (keeps costs low and responses concise).
_MAX_OUTPUT_TOKENS: int = 512

# ── Firestore singleton ───────────────────────────────────────────────────────
_db: Optional[firestore_client.Client] = None


def _get_db() -> firestore_client.Client:
    """Returns a lazily-initialised Firestore client (singleton).

    Returns:
        A shared ``firestore.Client`` instance for the current container.
    """
    global _db
    if _db is None:
        _db = firestore_client.Client()
    return _db


# ── Partisan refusal guard ────────────────────────────────────────────────────
# Keywords that indicate a user is asking for partisan political guidance.
# VoteWise India is strictly non-partisan and must refuse such queries.
PARTISAN_KEYWORDS: tuple[str, ...] = (
    "vote bjp", "vote congress", "vote aap", "vote tmc", "vote for",
    "modi", "rahul gandhi", "kejriwal", "mamata", "yogi", "nitish",
    "bjp", "congress party", "aam aadmi party", "shiv sena", "ncp", "bsp", "sp",
    "best party", "which party", "support party", "party better",
    "who should i vote", "endorse",
)


def check_for_refusal(message: str) -> Optional[str]:
    """Checks whether the user's message requires a non-partisan refusal.

    Scans the lower-cased message for any keyword from the
    ``PARTISAN_KEYWORDS`` tuple. If matched, returns the configured refusal
    template string; otherwise returns ``None``.

    Args:
        message: The raw user message string.

    Returns:
        A non-partisan refusal string if the message is partisan, else ``None``.
    """
    lower = message.lower()
    if any(kw in lower for kw in PARTISAN_KEYWORDS):
        return REFUSAL_TEMPLATES["partisan"]
    return None


# ── Firestore cache helpers ───────────────────────────────────────────────────

def _cache_key(message: str) -> str:
    """Derives a deterministic Firestore document key from a user message.

    The key is a SHA-256 hex digest of the normalised (stripped, lowercased)
    message, making cache lookups case- and whitespace-insensitive.

    Args:
        message: The raw user message string.

    Returns:
        A 64-character hex string suitable for a Firestore document ID.
    """
    return hashlib.sha256(message.strip().lower().encode()).hexdigest()


def _read_cache(message: str) -> Optional[dict]:
    """Attempts to read a cached Gemini reply from Firestore.

    Returns the cached document dictionary if it exists and is younger than
    ``CACHE_TTL_SECONDS``, incrementing its ``hit_count`` field atomically.
    Returns ``None`` on a cache miss, expiry, or any Firestore error.

    Args:
        message: The raw user message string (used to derive the cache key).

    Returns:
        The cached document dict on a hit, or ``None`` on a miss / error.
    """
    try:
        db = _get_db()
        ref = db.collection("cache").document(_cache_key(message))
        snap = ref.get()
        if snap.exists:
            data = snap.to_dict()
            age = time.time() - data.get("created_at", 0)
            if age < CACHE_TTL_SECONDS:
                ref.update({"hit_count": firestore_client.Increment(1)})
                return data
    except Exception as exc:
        logging.warning("Cache read error: %s", exc)
    return None


def _write_cache(message: str, reply: str, followups: list, source: str) -> None:
    """Persists a Gemini reply to the Firestore cache collection.

    Writes a new document under ``cache/{sha256_key}`` with the reply text,
    suggested follow-up questions, creation timestamp, and an initial hit
    counter. Failures are silently logged so caching never blocks a response.

    Args:
        message: The raw user message string (used to derive the cache key).
        reply: The Gemini-generated reply text.
        followups: A list of suggested follow-up question strings.
        source: One of ``"ai"``, ``"local"``, or ``"cache"``.
    """
    try:
        db = _get_db()
        ref = db.collection("cache").document(_cache_key(message))
        ref.set({
            "query": message.strip().lower(),
            "reply": reply,
            "suggested_followups": followups,
            "source": source,
            "created_at": time.time(),
            "hit_count": 0,
        })
    except Exception as exc:
        logging.warning("Cache write error: %s", exc)


# ── Vertex AI call ────────────────────────────────────────────────────────────

def _call_vertex(model_name: str, system_instruction: str, user_message: str) -> str:
    """Calls a Vertex AI Gemini model and returns the generated text.

    Initialises Vertex AI on first call, builds a ``GenerativeModel`` with the
    given system instruction, and invokes ``generate_content`` with a low-
    temperature generation config for factual accuracy.

    Args:
        model_name: The Vertex AI model name (e.g. ``"gemini-2.5-flash"``).
        system_instruction: The system-level instruction string for the model.
        user_message: The user's question or message text.

    Returns:
        The model's generated text response.

    Raises:
        Any exception raised by the Vertex AI SDK (caller handles retries).
    """
    _ensure_vertex_init()
    from vertexai.generative_models import GenerativeModel, GenerationConfig
    
    model = GenerativeModel(model_name, system_instruction=system_instruction)
    gen_cfg = GenerationConfig(temperature=_TEMPERATURE, max_output_tokens=_MAX_OUTPUT_TOKENS)
    response = model.generate_content(user_message, generation_config=gen_cfg)
    return response.text


# ── Offline fallback message ──────────────────────────────────────────────────
_OFFLINE_FALLBACK: str = (
    "⚠️ I'm having trouble reaching the AI service right now. "
    "For immediate help:\n\n"
    "- 🌐 Visit [voters.eci.gov.in](https://voters.eci.gov.in)\n"
    "- 📞 Call National Voter Helpline: **1950** (toll-free)\n"
    "- 🗳️ Visit [eci.gov.in](https://eci.gov.in) for official information"
)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_reply(user_message: str, grounded_context: dict) -> tuple[str, str]:
    """Generates a reply for the given user message using a 3-tier strategy.

    Tier order:
        1. **Partisan guard** — returns a refusal template immediately for
           politically biased questions (no AI cost).
        2. **Firestore cache** — returns a cached reply if one exists and is
           younger than ``CACHE_TTL_SECONDS`` (no AI cost).
        3. **Vertex AI** — calls the primary model, falling back to the
           secondary model on any error. Caches successful AI replies.

    If all AI calls fail, returns ``_OFFLINE_FALLBACK`` with ``source="local"``.

    Args:
        user_message: The raw, sanitised user message (max 500 chars enforced
            by the caller in ``main.py``).
        grounded_context: A dict of supplementary data (state deadlines, rules,
            language preference) built by the rules engine.

    Returns:
        A tuple ``(reply_text, source)`` where ``source`` is one of
        ``"local"``, ``"cache"``, or ``"ai"``.
    """
    # Guard: partisan refusal (zero-cost, instant).
    refusal = check_for_refusal(user_message)
    if refusal:
        return refusal, "local"

    # Guard: Firestore cache hit.
    cached = _read_cache(user_message)
    if cached:
        return cached["reply"], "cache"

    # Build system prompt and attempt Vertex AI calls in priority order.
    system_instruction = build_chat_prompt(grounded_context)

    for model_name in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            reply = _call_vertex(model_name, system_instruction, user_message)
            _write_cache(user_message, reply, [], "ai")
            return reply, "ai"
        except Exception as exc:
            logging.warning(
                "[VoteWise] Model %s failed: %s: %s",
                model_name, type(exc).__name__, exc,
            )

    return _OFFLINE_FALLBACK, "local"
