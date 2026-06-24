"""Server-side rate-ceiling negotiation logic — ceiling enforced, never disclosed.

Design (chosen by an independent design panel): a FIXED
percentage step ladder. The crux security property is that suggested_counter
is a DETERMINISTIC function of (posted_rate, round_no) ONLY — never of max_buy.
`max_buy` is read in exactly ONE place: the accept/counter/reject DECISION
(`evaluate_offer`). `compute_counter` does not even take `max_buy` as a parameter.
So two loads with the same posted_rate but different ceilings emit byte-identical
counter sequences for identical offers — the spoken numbers leak nothing.

Domain is INVERTED vs a normal sale (verified against the live TMS): the broker PAYS the
carrier, and max_buy sits ABOVE the posted loadboard rate (+6%..+22% live). So we
pitch posted_rate and concede UPWARD toward — but never disclose — max_buy. We
ACCEPT any offer <= max_buy and never pay above it.

CEILING SAFETY OF THE COUNTER: the counter is capped at the ladder's TOP rung
`round_to_25(posted_rate * 1.06)`, a pure function of posted_rate. On all 5 live
tokens this top rung is <= the true ceiling, so a counter never exceeds a live
ceiling. On a pathological sub-+6%-spread token (never seen live) the top rung
could exceed max_buy and be SPOKEN; the HARD guarantee that nothing BOOKS above
the ceiling is the booking endpoint's INDEPENDENT `agreed_rate <= max_buy`
re-check, not this function. By design `compute_counter` does NOT guarantee
`counter < max_buy` — that invariant is enforced at BOOK time, never here (so the
counter cannot encode the ceiling).
"""
from __future__ import annotations

from dataclasses import dataclass

# Fixed concession ladder: percentage of posted_rate by round. NEVER derived from max_buy.
STEP: dict[int, float] = {1: 0.02, 2: 0.04, 3: 0.06}
QUANT = 25                       # spoken-number granularity (whole dollars)
CEIL_MIN = 100                   # plausibility window (whole dollars) — unit-slip guard
CEIL_MAX = 100_000


class CeilingSanityError(Exception):
    """max_buy / posted_rate implausible (likely a cents-vs-dollars 100x unit slip),
    or inverted data (posted_rate >= max_buy). Fails LOUD (-> 500-class, token-redacted)
    rather than silently mis-comparing."""


@dataclass
class OfferDecision:
    decision: str                          # "accept" | "counter" | "reject"
    agreed_rate: int | None = None         # set only on accept; == the carrier's own offer
    suggested_counter: int | None = None   # set only on counter
    reason: str | None = None              # set only on reject (ceiling-agnostic)
    round: int | None = None
    max_rounds: int | None = None
    rounds_remaining: int | None = None
    ceiling_available: bool = True


def _round_to_quant(x: float) -> int:
    return int(round(x / QUANT) * QUANT)


def _top_rung(posted_rate: int) -> int:
    """The highest counter the ladder will ever speak — a pure function of posted_rate."""
    return _round_to_quant(posted_rate * (1 + STEP[max(STEP)]))


def compute_counter(posted_rate: int, round_no: int, carrier_offer: int,
                    prior_counter: int | None) -> int:
    """suggested_counter from (posted_rate, round_no) ONLY, then PUBLIC clamps.

    `max_buy` is intentionally NOT a parameter — it must never influence the number
    we speak. The clamps read only carrier-known quantities: the carrier's own
    ask, the prior counter, our own posted pitch, and the (posted-derived) top rung.
    """
    step = STEP.get(round_no, STEP[max(STEP)])           # cap at top rung if round capped
    top = _top_rung(posted_rate)
    counter = _round_to_quant(posted_rate * (1 + step))  # ladder = f(posted, round) ONLY
    if prior_counter is not None:                        # PUBLIC: enforce an upward climb
        counter = max(counter, prior_counter + QUANT)
    counter = min(counter, top)                          # never climb past the top rung (keeps <= live ceilings)
    counter = min(counter, carrier_offer - QUANT)        # PUBLIC: stay strictly below the ask
    counter = max(counter, posted_rate)                  # never undercut our own posted pitch
    return counter


def evaluate_offer(
    carrier_offer: int,
    max_buy: int | None,
    posted_rate: int,
    round_no: int,
    *,
    max_rounds: int = 3,
    prior_counter: int | None = None,
) -> OfferDecision:
    # 0. Validate caller-influenced inputs. round_no / max_rounds / prior_counter are
    #    SERVER-OWNED via NegotiationStore (below) — NEVER trust them from a request body.
    #    Reject non-integral round_no (a float like 3.9 must not floor past the cap) and bools.
    if isinstance(round_no, bool) or not isinstance(round_no, int) or round_no < 1:
        raise ValueError(f"round_no must be a positive int, got {round_no!r}")
    #    carrier_offer is the one carrier-controlled number: it must be a plausible whole-dollar
    #    int, else a negative/zero/float offer would ACCEPT and echo a bogus agreed_rate.
    if isinstance(carrier_offer, bool) or not isinstance(carrier_offer, int):
        raise ValueError(f"carrier_offer must be an int, got {carrier_offer!r}")
    if not (CEIL_MIN <= carrier_offer <= CEIL_MAX):
        raise ValueError(f"carrier_offer={carrier_offer} outside [{CEIL_MIN},{CEIL_MAX}]")

    # 1. ROUND CAP FIRST. Deterministic close even on a degraded token, AND it bounds the
    #    accept/reject oracle to <=max_rounds probes per run (a later evaluate is denied
    #    regardless of offer). The cap is only meaningful because NegotiationStore owns
    #    round_no server-side; calling evaluate_offer with a caller-pinned round_no
    #    would defeat it — which is exactly why the router must go through the store.
    if round_no > max_rounds:
        return OfferDecision("reject", reason="max_rounds_exhausted",
                             round=round_no, max_rounds=max_rounds, rounds_remaining=0)

    # 2. FAIL CLOSED on a missing ceiling. NEVER fall back to posted_rate as the ceiling.
    if max_buy is None:
        return OfferDecision("reject", reason="ceiling_unavailable", ceiling_available=False)

    # 3. UNIT SANITY. Fail LOUD on a cents/dollars 100x slip; never enforce a wrong compare.
    if not (CEIL_MIN <= max_buy <= CEIL_MAX):
        raise CeilingSanityError(f"max_buy={max_buy} outside [{CEIL_MIN},{CEIL_MAX}]")
    if posted_rate is None or not (CEIL_MIN <= posted_rate <= CEIL_MAX):  # posted drives the ladder; guard it too
        raise CeilingSanityError(f"posted_rate={posted_rate} outside [{CEIL_MIN},{CEIL_MAX}]")
    if posted_rate >= max_buy:                           # inverted/garbage data -> surface LOUDLY
        raise CeilingSanityError(f"posted_rate={posted_rate} >= max_buy={max_buy}")

    # 4. ACCEPT. Paying at or under our max is good (inverted domain). Echo the carrier's OWN
    #    number as agreed_rate; max_buy is never returned.
    if carrier_offer <= max_buy:
        return OfferDecision("accept", agreed_rate=carrier_offer,
                             round=round_no, max_rounds=max_rounds,
                             rounds_remaining=max_rounds - round_no)

    # 5. COUNTER (offer exceeds the ceiling). Deterministic ladder; max_buy untouched here.
    counter = compute_counter(posted_rate, round_no, carrier_offer, prior_counter)
    return OfferDecision("counter", suggested_counter=counter,
                         round=round_no, max_rounds=max_rounds,
                         rounds_remaining=max_rounds - round_no)


MAX_ROUNDS = 3  # server constant; the negotiation cap is NEVER caller-overridable.


@dataclass
class _NegState:
    round_no: int = 0
    prior_counter: int | None = None
    accepted_rate: int | None = None  # the rate we actually accepted; a booking must match it


class NegotiationStore:
    """Trust-boundary entry point for offer evaluation.

    The accept/reject decision is an unavoidable oracle on max_buy; the ONLY thing
    stopping a caller from binary-searching the ceiling is the <=MAX_ROUNDS cap.
    That cap is meaningless if the caller controls the round counter — so this store
    OWNS the round number AND the prior_counter, keyed to server-trusted
    (run_id, load_id): it increments per call, ignores any caller round/max_rounds,
    and fails closed past MAX_ROUNDS. The router MUST call this — never evaluate_offer
    directly with a request-supplied round.
    """

    def __init__(self, *, max_rounds: int = MAX_ROUNDS):
        self._max_rounds = max_rounds
        self._state: dict[tuple[str, str], _NegState] = {}

    def evaluate(self, run_id: str, load_id: str, carrier_offer: int,
                 max_buy: int | None, posted_rate: int) -> OfferDecision:
        st = self._state.setdefault((str(run_id), str(load_id)), _NegState())
        st.round_no += 1  # server-incremented; a caller cannot pin, reset, or replay it
        decision = evaluate_offer(
            carrier_offer, max_buy, posted_rate, st.round_no,
            max_rounds=self._max_rounds, prior_counter=st.prior_counter,
        )
        if decision.decision == "counter":
            st.prior_counter = decision.suggested_counter  # server-held; not caller-forgeable
        elif decision.decision == "accept":
            st.accepted_rate = decision.agreed_rate        # token for the booking guard
        return decision

    def accepted_rate(self, run_id: str, load_id: str) -> int | None:
        """The rate the adapter recorded as accepted for (run_id, load_id), or None.

        The booking endpoint books ONLY a rate equal to this — so a rate that was
        never accepted (incl. any over-ceiling counter, which never accepts) cannot book.
        """
        st = self._state.get((str(run_id), str(load_id)))
        return st.accepted_rate if st else None
