"""Ceiling-logic tests — encodes the attack surface from the design workflow.

Central invariant under test: suggested_counter is a pure function of
(posted_rate, round_no) and carries ZERO information about max_buy.
"""
import inspect
from dataclasses import asdict

import pytest

from app.services.ceiling import (
    CEIL_MAX,
    CEIL_MIN,
    MAX_ROUNDS,
    CeilingSanityError,
    NegotiationStore,
    OfferDecision,
    compute_counter,
    evaluate_offer,
    _top_rung,
)

# (posted_rate, max_buy) for the 5 live TMS tokens.
LIVE_TOKENS = [(714, 757), (1704, 1999), (1968, 2355), (4247, 4736), (4360, 5298)]


def _run_sequence(offers, max_buy, posted_rate, max_rounds=3):
    """Drive a multi-round negotiation, threading the server-held prior_counter."""
    out, prior = [], None
    for i, offer in enumerate(offers, start=1):
        d = evaluate_offer(offer, max_buy, posted_rate, i, max_rounds=max_rounds, prior_counter=prior)
        out.append(d)
        if d.decision == "counter":
            prior = d.suggested_counter
    return out


# --------------------------- non-leak (the crux) --------------------------- #
def test_compute_counter_has_no_max_buy_parameter():
    # Structural guard: a future edit cannot thread max_buy into the counter math.
    assert "max_buy" not in inspect.signature(compute_counter).parameters


def test_identical_counters_for_same_posted_different_ceiling_offers_above_all():
    # Offers exceed every ceiling -> all rounds counter -> sequences must be byte-identical.
    offers = [9000, 9000, 9000]
    seqs = {
        mb: [d.suggested_counter for d in _run_sequence(offers, mb, 1704)]
        for mb in (1780, 1999, 5000)
    }
    assert seqs[1780] == seqs[1999] == seqs[5000] == [1750, 1775, 1800]


def test_counters_identical_where_both_counter_realistic_offers():
    # Diverge ONLY at the accept/counter boundary; counter VALUES never differ by ceiling.
    offers = [2100, 2000, 1950]
    a = _run_sequence(offers, 1999, 1704)
    b = _run_sequence(offers, 1780, 1704)
    for da, db in zip(a, b):
        if da.decision == "counter" and db.decision == "counter":
            assert da.suggested_counter == db.suggested_counter
    # r3 is the irreducible boundary: 1950 <= 1999 accepts, 1950 > 1780 counters.
    assert a[2].decision == "accept" and b[2].decision == "counter"


# ------------------------------- accept rule ------------------------------- #
def test_accept_when_offer_at_or_below_ceiling_echoes_offer():
    d = evaluate_offer(1990, 1999, 1704, 1)
    assert d.decision == "accept" and d.agreed_rate == 1990


def test_offer_equal_to_ceiling_accepts_inclusive():
    d = evaluate_offer(1999, 1999, 1704, 1)
    assert d.decision == "accept" and d.agreed_rate == 1999


def test_offer_one_above_ceiling_counters():
    d = evaluate_offer(2000, 1999, 1704, 1)
    assert d.decision == "counter"


# ------------------------------- counter shape ----------------------------- #
def test_counter_strictly_below_carrier_ask():
    for offer in (2000, 2100, 5000):
        d = evaluate_offer(offer, 1999, 1704, 1)
        if d.decision == "counter":
            assert d.suggested_counter < offer


def test_counter_at_or_above_posted_and_at_or_below_top_rung():
    top = _top_rung(1704)
    for r in (1, 2, 3):
        d = evaluate_offer(9000, 1999, 1704, r, prior_counter={1: None, 2: 1750, 3: 1775}[r])
        assert 1704 <= d.suggested_counter <= top


def test_counters_climb_monotonically():
    seq = [d.suggested_counter for d in _run_sequence([9000, 9000, 9000], 1999, 1704)]
    assert seq[0] <= seq[1] <= seq[2]


def test_counter_stays_at_or_below_ceiling_on_all_live_tokens():
    # The top-rung cap (round_to_25(posted*1.06)) keeps the spoken counter <= the
    # real ceiling on every live token, so nothing over-ceiling is ever SPOKEN live.
    for posted, max_buy in LIVE_TOKENS:
        for d in _run_sequence([99999, 99999, 99999], max_buy, posted):
            assert d.suggested_counter <= max_buy


# ----------------------------- fail-closed --------------------------------- #
def test_missing_ceiling_fails_closed_never_accepts():
    d = evaluate_offer(1800, None, 1704, 1)
    assert d.decision == "reject" and d.reason == "ceiling_unavailable"
    assert d.ceiling_available is False
    assert d.agreed_rate is None and d.suggested_counter is None


# ------------------------------ unit sanity -------------------------------- #
@pytest.mark.parametrize("max_buy", [19, 99, 199900, CEIL_MAX + 1])
def test_implausible_ceiling_raises_loud(max_buy):
    with pytest.raises(CeilingSanityError):
        evaluate_offer(2000, max_buy, 1704, 1)


def test_implausible_posted_raises_loud():
    with pytest.raises(CeilingSanityError):
        evaluate_offer(2000, 1999, 99, 1)


def test_inverted_data_posted_ge_ceiling_raises_loud():
    with pytest.raises(CeilingSanityError):
        evaluate_offer(2000, 1700, 1800, 1)  # posted >= max_buy


# ------------------------------- round cap --------------------------------- #
def test_round_past_cap_rejects_even_for_acceptable_offer():
    # The oracle defense (pure-function level): a 4th probe is denied REGARDLESS of offer.
    d = evaluate_offer(1000, 1999, 1704, 4)  # 1000 <= 1999 would otherwise accept
    assert d.decision == "reject" and d.reason == "max_rounds_exhausted"
    assert d.agreed_rate is None and d.suggested_counter is None


def test_final_allowed_round_still_evaluates():
    assert evaluate_offer(1990, 1999, 1704, 3).decision == "accept"


def test_round_below_one_is_invalid():
    with pytest.raises(ValueError):
        evaluate_offer(1990, 1999, 1704, 0)


def test_non_integral_round_no_is_invalid():
    # 3.9 must NOT floor to 3 and slip a 4th probe past the cap.
    with pytest.raises(ValueError):
        evaluate_offer(1000, 1999, 1704, 3.9)


# ------------------- carrier_offer validation (the carrier-controlled input) ---- #
@pytest.mark.parametrize("offer", [-100, 0, 99, CEIL_MAX + 1, 1800.5, True])
def test_implausible_or_nonintegral_offer_is_rejected(offer):
    with pytest.raises(ValueError):
        evaluate_offer(offer, 1999, 1704, 1)


# ----------- NegotiationStore: server-owned round state (the real cap defense) -- #
def test_store_caps_probes_defeating_binary_search():
    # With caller-controlled round_no a binary search recovers max_buy in ~17 probes.
    # Through the store, the SAME (run_id, load_id) is hard-capped at MAX_ROUNDS probes:
    # the (MAX_ROUNDS+1)-th evaluate is rejected regardless of offer, starving the oracle.
    store = NegotiationStore()
    decisions = [store.evaluate("run1", "LD1", 5000, 1999, 1704) for _ in range(MAX_ROUNDS + 1)]
    assert decisions[-1].decision == "reject" and decisions[-1].reason == "max_rounds_exhausted"
    # An acceptable offer on the (cap+1)-th call is STILL refused -> no extra probe.
    assert store.evaluate("run1", "LD1", 1000, 1999, 1704).decision == "reject"


def test_store_evaluate_exposes_no_round_or_max_rounds_knob():
    # The trust-boundary API must not let a caller supply round_no/max_rounds at all.
    import inspect
    params = set(inspect.signature(NegotiationStore.evaluate).parameters)
    assert params == {"self", "run_id", "load_id", "carrier_offer", "max_buy", "posted_rate"}


def test_store_tracks_round_and_prior_counter_server_side():
    store = NegotiationStore()
    d1 = store.evaluate("run1", "LD1", 2150, 1999, 1704)
    d2 = store.evaluate("run1", "LD1", 2050, 1999, 1704)
    d3 = store.evaluate("run1", "LD1", 1990, 1999, 1704)
    assert (d1.round, d2.round, d3.round) == (1, 2, 3)
    assert d1.suggested_counter == 1750 and d2.suggested_counter == 1775
    assert d3.decision == "accept" and d3.agreed_rate == 1990


def test_store_keys_round_state_per_run_and_load():
    store = NegotiationStore()
    store.evaluate("run1", "LD1", 5000, 1999, 1704)
    # A different load (or run) starts its own fresh round counter.
    assert store.evaluate("run1", "LD2", 5000, 1999, 1704).round == 1
    assert store.evaluate("run2", "LD1", 5000, 1999, 1704).round == 1


# --------------------------- non-disclosure -------------------------------- #
def test_ceiling_value_never_appears_in_any_decision():
    cases = [
        evaluate_offer(1990, 1999, 1704, 1),   # accept
        evaluate_offer(2100, 1999, 1704, 1),   # counter
        evaluate_offer(1000, 1999, 1704, 4),   # reject (rounds)
        evaluate_offer(1800, None, 1704, 1),   # reject (no ceiling)
    ]
    for d in cases:
        assert 1999 not in [v for v in asdict(d).values() if isinstance(v, int)]


def test_demo_token_worked_example():
    # LD00271 (posted 1704 / max_buy 1999): pitch low, concede up, accept within budget.
    seq = _run_sequence([2150, 2050, 1990], 1999, 1704)
    assert seq[0].decision == "counter" and seq[0].suggested_counter == 1750
    assert seq[1].decision == "counter" and seq[1].suggested_counter == 1775
    assert seq[2].decision == "accept" and seq[2].agreed_rate == 1990
