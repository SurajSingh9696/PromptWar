"""
Unit tests for VoteWise India rules engine.

Tests cover:
    - check_eligibility — age/citizenship boundary conditions
    - get_deadlines     — known and unknown state lookups
    - get_state_rules   — state rules structure
    - find_local_answer — keyword matching for all topic categories
"""

import pytest
from functions.rules_engine import (
    check_eligibility,
    get_deadlines,
    get_state_rules,
    find_local_answer,
    LOCAL_ANSWERS,
)


# ---------------------------------------------------------------------------
# check_eligibility
# ---------------------------------------------------------------------------

class TestCheckEligibility:
    def test_underage_17_is_ineligible(self):
        res = check_eligibility(17, True, "DL")
        assert res["eligible"] is False
        assert any("18" in r for r in res["reasons"])

    def test_boundary_age_18_is_eligible(self):
        """Exactly 18 must be eligible."""
        res = check_eligibility(18, True, "DL")
        assert res["eligible"] is True

    def test_non_citizen_is_ineligible(self):
        res = check_eligibility(25, False, "MH")
        assert res["eligible"] is False
        assert any("citizen" in r.lower() for r in res["reasons"])

    def test_valid_adult_citizen_is_eligible(self):
        res = check_eligibility(25, True, "KA")
        assert res["eligible"] is True

    def test_eligible_result_has_next_steps(self):
        res = check_eligibility(30, True, "GJ")
        assert len(res["next_steps"]) > 0

    def test_ineligible_result_has_next_steps(self):
        res = check_eligibility(15, False, "TN")
        assert res["eligible"] is False
        assert len(res["next_steps"]) > 0

    def test_zero_age_is_ineligible(self):
        res = check_eligibility(0, True, "DL")
        assert res["eligible"] is False

    def test_maximum_valid_age(self):
        res = check_eligibility(150, True, "DL")
        assert res["eligible"] is True

    def test_dual_disqualification_both_reasons_present(self):
        """Minor AND non-citizen should have two failure reasons."""
        res = check_eligibility(10, False, "UP")
        assert res["eligible"] is False
        assert len(res["reasons"]) >= 2


# ---------------------------------------------------------------------------
# get_deadlines
# ---------------------------------------------------------------------------

class TestGetDeadlines:
    def test_known_state_delhi(self):
        res = get_deadlines("DL")
        assert "error" not in res
        assert res["state_name"] is not None

    def test_known_state_lowercase(self):
        """Lowercase state code should be accepted."""
        res = get_deadlines("dl")
        assert "error" not in res

    def test_unknown_state_returns_error(self):
        res = get_deadlines("XX")
        assert "error" in res

    def test_result_contains_required_keys(self):
        res = get_deadlines("DL")
        for key in ("state_name", "last_election_date", "next_election_due"):
            assert key in res, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# get_state_rules
# ---------------------------------------------------------------------------

class TestGetStateRules:
    def test_known_state_returns_rules(self):
        res = get_state_rules("DL")
        assert "error" not in res
        assert "state_name" in res

    def test_known_state_has_alternative_ids(self):
        res = get_state_rules("MH")
        assert "alternative_ids_accepted" in res

    def test_unknown_state_returns_error(self):
        res = get_state_rules("ZZ")
        assert "error" in res


# ---------------------------------------------------------------------------
# find_local_answer
# ---------------------------------------------------------------------------

class TestFindLocalAnswer:
    @pytest.mark.parametrize("query,expected_topic", [
        ("how old do i need to be to vote", "age_requirement"),
        ("minimum age requirement for voting", "age_requirement"),
        ("nri vote in india", "citizenship"),
        ("how to register to vote in india", "registration"),
        ("what is form 6", "registration"),
        ("forgot to register for elections", "registration"),
        ("what is epic card", "voter_id"),
        ("alternative id at polling booth", "alternative_id"),
        ("how do evms work", "evm"),
        ("what is vvpat", "evm"),
        ("check my name on voter list", "check_name"),
        ("where to vote polling station", "polling_booth"),
        ("what is model code of conduct", "model_code"),
        ("how to use cvigil app", "cvigil"),
        ("when is the next lok sabha election", "lok_sabha"),
        ("what is vidhan sabha", "vidhan_sabha"),
        ("is this data accurate", "disclaimer"),
        ("unable to vote what are reasons", "unable_to_vote"),
        ("name not on voter list", "name_not_on_roll"),
        ("i changed address how to update", "address_change"),
        ("contact eci helpline", "eci_contact"),
    ])
    def test_keyword_matches_correct_topic(self, query, expected_topic):
        """Each query must return the expected pre-built answer."""
        answer = find_local_answer(query)
        # Verify we get something back (not None)
        assert answer is not None, f"Expected a local answer for: '{query}'"
        # Cross-check: the answer content should match the expected topic's text
        expected_answer = LOCAL_ANSWERS[expected_topic][1]
        assert answer == expected_answer, (
            f"For query '{query}', got answer for wrong topic.\n"
            f"Expected snippet: {expected_answer[:60]!r}\n"
            f"Got:              {answer[:60]!r}"
        )

    def test_unrelated_query_returns_none(self):
        assert find_local_answer("What is the weather today?") is None

    def test_empty_string_returns_none(self):
        assert find_local_answer("") is None

    def test_case_insensitive_matching(self):
        """Keywords must match regardless of input case."""
        assert find_local_answer("HOW TO REGISTER TO VOTE") is not None
