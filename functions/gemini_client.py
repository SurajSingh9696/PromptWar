"""
VoteWise India — Gemini API client (standalone, no Firebase dependencies).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from threading import Lock
from typing import Optional

from google import genai
from google.genai import types

try:
    from .prompts import REFUSAL_TEMPLATES, build_chat_prompt
except ImportError:
    from prompts import REFUSAL_TEMPLATES, build_chat_prompt

PRIMARY_MODEL: str = os.environ.get("ACTIVE_MODEL", "gemini-2.5-flash")
FALLBACK_MODEL: str = os.environ.get("FALLBACK_MODEL", "gemini-1.5-flash")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "").strip()

CACHE_TTL_SECONDS: int = 60 * 60
_TEMPERATURE: float = 0.2
_MAX_OUTPUT_TOKENS: int = 512
_client: Optional[genai.Client] = None
_cache_lock: Lock = Lock()
_memory_cache: dict[str, dict] = {}

PARTISAN_KEYWORDS: tuple[str, ...] = (
    "vote bjp",
    "vote congress",
    "vote aap",
    "vote tmc",
    "vote for",
    "modi",
    "rahul gandhi",
    "kejriwal",
    "mamata",
    "yogi",
    "nitish",
    "bjp",
    "congress party",
    "aam aadmi party",
    "shiv sena",
    "ncp",
    "bsp",
    "sp",
    "best party",
    "which party",
    "support party",
    "party better",
    "who should i vote",
    "endorse",
)

_OFFLINE_FALLBACK: str = (
    "⚠️ I'm having trouble reaching the AI service right now. "
    "For immediate help:\n\n"
    "- 🌐 Visit [voters.eci.gov.in](https://voters.eci.gov.in)\n"
    "- 📞 Call National Voter Helpline: **1950** (toll-free)\n"
    "- 🗳️ Visit [eci.gov.in](https://eci.gov.in) for official information"
)


def _get_client() -> Optional[genai.Client]:
    global _client
    if _client is not None:
        return _client
    if not GEMINI_API_KEY:
        return None
    _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def check_for_refusal(message: str) -> Optional[str]:
    lower = message.lower()
    if any(kw in lower for kw in PARTISAN_KEYWORDS):
        return REFUSAL_TEMPLATES["partisan"]
    return None


def _cache_key(message: str) -> str:
    return hashlib.sha256(message.strip().lower().encode()).hexdigest()


def _read_cache(message: str) -> Optional[dict]:
    key = _cache_key(message)
    now = time.time()
    with _cache_lock:
        item = _memory_cache.get(key)
        if not item:
            return None
        if now - item.get("created_at", 0) >= CACHE_TTL_SECONDS:
            _memory_cache.pop(key, None)
            return None
        item["hit_count"] = int(item.get("hit_count", 0)) + 1
        return item


def _write_cache(message: str, reply: str, followups: list[str], source: str) -> None:
    key = _cache_key(message)
    with _cache_lock:
        _memory_cache[key] = {
            "query": message.strip().lower(),
            "reply": reply,
            "suggested_followups": followups,
            "source": source,
            "created_at": time.time(),
            "hit_count": 0,
        }


def _extract_text(response: object) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        parts = getattr(candidates[0], "content", None)
        if parts and getattr(parts, "parts", None):
            assembled = []
            for part in parts.parts:
                maybe_text = getattr(part, "text", "")
                if maybe_text:
                    assembled.append(maybe_text)
            if assembled:
                return "\n".join(assembled).strip()
    return ""


def _call_gemini(model_name: str, system_instruction: str, user_message: str) -> str:
    client = _get_client()
    if client is None:
        raise RuntimeError("Gemini API key is not configured")
    response = client.models.generate_content(
        model=model_name,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=_TEMPERATURE,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
        ),
    )
    text = _extract_text(response)
    if not text:
        raise RuntimeError("Empty Gemini response")
    return text


def generate_reply(user_message: str, grounded_context: dict) -> tuple[str, str]:
    refusal = check_for_refusal(user_message)
    if refusal:
        return refusal, "local"

    cached = _read_cache(user_message)
    if cached:
        return cached["reply"], "cache"

    if not GEMINI_API_KEY:
        logging.warning("GEMINI_API_KEY not set. Returning fallback response.")
        return _OFFLINE_FALLBACK, "local"

    system_instruction = build_chat_prompt(grounded_context)
    for model_name in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            reply = _call_gemini(model_name, system_instruction, user_message)
            _write_cache(user_message, reply, [], "ai")
            return reply, "ai"
        except Exception as exc:
            logging.warning(
                "[VoteWise] Model %s failed: %s: %s",
                model_name,
                type(exc).__name__,
                exc,
            )

    return _OFFLINE_FALLBACK, "local"
