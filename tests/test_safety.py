"""
Unit tests for VoteWise India partisan-safety guard (gemini_client).

Tests cover:
    - check_for_refusal — exact keyword matches, partial matches, edge cases
    - _cache_key        — determinism and normalisation
    - build_chat_prompt (via prompts) — context injection
"""

import pytest
from functions.gemini_client import check_for_refusal, PARTISAN_KEYWORDS, _cache_key
from functions.prompts import build_chat_prompt, REFUSAL_TEMPLATES


# ---------------------------------------------------------------------------
# check_for_refusal
# ---------------------------------------------------------------------------

class TestCheckForRefusal:
    @pytest.mark.parametrize("message", [
        "vote bjp this time",
        "which is the best party in india",
        "should i vote for congress",
        "tell me about modi government",
        "I think rahul gandhi should be PM",
        "BJP is the best party in india",
        "endorse BJP please",
    ])
    def test_partisan_messages_are_refused(self, message: str):
        result = check_for_refusal(message)
        assert result is not None, f"Expected refusal for: '{message}'"
        assert len(result) > 0

    @pytest.mark.parametrize("message", [
        "How do I register to vote?",
        "What documents do I need at the polling booth?",
        "When is the next election in Delhi?",
        "What is EPIC card?",
        "Can I vote without voter ID?",
        "What is the Model Code of Conduct?",
        "EVM kya hota hai",
        "How do I check my name on the voter list?",
    ])
    def test_neutral_messages_are_not_refused(self, message: str):
        result = check_for_refusal(message)
        assert result is None, f"Should NOT be refused: '{message}'"

    def test_returns_refusal_string(self):
        """Refusal text should match the configured partisan template."""
        result = check_for_refusal("vote bjp")
        assert result == REFUSAL_TEMPLATES["partisan"]

    def test_case_insensitive_matching(self):
        """Partisan detection must be case-insensitive."""
        assert check_for_refusal("VOTE BJP NOW") is not None
        assert check_for_refusal("Vote Congress") is not None
        assert check_for_refusal("ENDORSE AAP") is not None

    def test_empty_string_is_not_refused(self):
        """Empty string should not trigger refusal."""
        assert check_for_refusal("") is None

    def test_all_keywords_are_caught(self):
        """Every keyword in PARTISAN_KEYWORDS must trigger a refusal."""
        for kw in PARTISAN_KEYWORDS:
            result = check_for_refusal(f"I want to {kw}")
            assert result is not None, f"Keyword '{kw}' did not trigger refusal"


# ---------------------------------------------------------------------------
# _cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_deterministic(self):
        k1 = _cache_key("How do I vote?")
        k2 = _cache_key("How do I vote?")
        assert k1 == k2

    def test_normalises_case(self):
        assert _cache_key("HOW DO I VOTE") == _cache_key("how do i vote")

    def test_normalises_whitespace(self):
        assert _cache_key("  how do i vote  ") == _cache_key("how do i vote")

    def test_produces_hex_string(self):
        key = _cache_key("test")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_different_messages_produce_different_keys(self):
        assert _cache_key("message one") != _cache_key("message two")


# ---------------------------------------------------------------------------
# build_chat_prompt (via prompts module)
# ---------------------------------------------------------------------------

class TestBuildChatPrompt:
    def test_no_context_returns_generic_prompt(self):
        prompt = build_chat_prompt({})
        assert "No specific state selected" in prompt

    def test_state_deadlines_injected(self):
        ctx = {"state_deadlines": {"state_name": "Delhi", "next_election_due": "2025-02"}}
        prompt = build_chat_prompt(ctx)
        assert "Delhi" in prompt

    def test_state_rules_injected(self):
        ctx = {"state_rules": {"epic_required": True}}
        prompt = build_chat_prompt(ctx)
        assert "epic_required" in prompt

    def test_language_instruction_added_for_hindi(self):
        ctx = {"language": "Hindi"}
        prompt = build_chat_prompt(ctx)
        assert "Hindi" in prompt

    def test_no_language_instruction_for_english(self):
        ctx = {"language": "English"}
        prompt = build_chat_prompt(ctx)
        # English is the default — no extra language instruction appended.
        assert "IMPORTANT: Respond in English" not in prompt

    def test_irrelevant_keys_excluded(self):
        """Keys like 'user_id' or 'session' must not appear in the prompt."""
        ctx = {
            "user_id": "abc123",
            "session": "xyz",
            "state_deadlines": {"state_name": "Delhi"},
        }
        prompt = build_chat_prompt(ctx)
        assert "user_id" not in prompt
        assert "session" not in prompt
