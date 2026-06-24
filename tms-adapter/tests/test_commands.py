from pathlib import Path

import pytest

from app.tms.client import TMSClient
from app.tms.commands import TMSCommands
from app.tms.errors import TMSError
from app.tms.faults import TMSFaultError
from fake_tms.server import Reply, run_fake_tms

TRANSCRIPTS = Path(__file__).resolve().parent / "fixtures" / "transcripts"
LD271 = (TRANSCRIPTS / "loadget_LD00271.txt").read_bytes()
QUERY_AL = (TRANSCRIPTS / "query_orig_AL.txt").read_bytes()
CO_MALFORMED = (TRANSCRIPTS / "query_orig_CO.txt").read_bytes()  # live malformed-fault capture

BOOK_OK = b"LOAD_ID:LD00271     |STATUS:BOOKED  |BOOKING_REF:BR00000000091277\r\nEND\r\n"
GET_BOOKED = LD271.replace(b"STATUS:OPEN    ", b"STATUS:BOOKED  ")  # same widths


def _cmds(port: int, **kw) -> TMSCommands:
    client = TMSClient("127.0.0.1", port, "T", deadline_s=0.4, connect_timeout_s=0.3, read_timeout_s=0.3)
    return TMSCommands(client, backoff=(0, 0), jitter=False, **kw)  # no sleeps in tests


# --------------------------------- reads ----------------------------------- #
async def test_load_get_clean():
    async with run_fake_tms(lambda req: Reply(LD271)) as s:
        rec = await _cmds(s.port).load_get("LD00271")
    assert rec["RATE"] == 1704 and rec["MAX_BUY"] == 1999


async def test_load_get_strips_padded_id_before_sending():
    async with run_fake_tms(lambda req: Reply(LD271)) as s:
        await _cmds(s.port).load_get("LD00271     ")  # space-padded width-12 id
        assert s.requests[0]["fields"]["LOAD_ID"] == "LD00271"


async def test_load_get_not_found_is_404_and_not_retried():
    err = b"ERR|CODE:NOT_FOUND|MSG:no such load\r\n"
    async with run_fake_tms(lambda req: Reply(err)) as s:
        with pytest.raises(TMSError) as e:
            await _cmds(s.port).load_get("LDZZZ")
        assert s.count("LOAD_GET") == 1  # deterministic error -> NOT retried
    assert e.value.code == "NOT_FOUND" and e.value.http_status == 404


async def test_load_query_returns_records():
    async with run_fake_tms(lambda req: Reply(QUERY_AL)) as s:
        loads = await _cmds(s.port).load_query(ORIG_STATE="AL")
    assert len(loads) == 2 and loads[0]["ORIG_STATE"] == "AL"


async def test_load_query_empty_board():
    async with run_fake_tms(lambda req: Reply(b"END\r\n")) as s:
        loads = await _cmds(s.port).load_query(ORIG_STATE="ZZ")
    assert loads == []


async def test_read_retries_recover_from_live_malformed_capture():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        return Reply(CO_MALFORMED) if state["n"] == 1 else Reply(QUERY_AL)

    async with run_fake_tms(handler) as s:
        loads = await _cmds(s.port).load_query(ORIG_STATE="CO")
    assert len(loads) == 2 and state["n"] == 2  # one retry recovered


async def test_read_gives_up_after_exhausting_attempts():
    async with run_fake_tms(lambda req: Reply(CO_MALFORMED)) as s:
        with pytest.raises(TMSFaultError):
            await _cmds(s.port, read_attempts=3).load_query(ORIG_STATE="CO")
        assert s.count("LOAD_QUERY") == 3


async def test_server_error_is_retryable():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        return Reply(b"ERR|CODE:SERVER_ERROR|MSG:busy\r\n") if state["n"] == 1 else Reply(QUERY_AL)

    async with run_fake_tms(handler) as s:
        loads = await _cmds(s.port).load_query(ORIG_STATE="AL")
    assert len(loads) == 2 and state["n"] == 2


# -------------------------------- booking ---------------------------------- #
async def test_book_clean_returns_ref():
    async with run_fake_tms(lambda req: Reply(BOOK_OK)) as s:
        res = await _cmds(s.port).load_book("LD00271", "872144", 1900)
        assert s.count("LOAD_BOOK") == 1
    assert res.status == "booked" and res.confirmed is True
    assert res.booking_ref == "BR00000000091277"


async def test_book_invalid_rate_is_deterministic_no_resend():
    async with run_fake_tms(lambda req: Reply(b"ERR|CODE:INVALID_RATE|MSG:too low\r\n")) as s:
        with pytest.raises(TMSError) as e:
            await _cmds(s.port).load_book("LD00271", "872144", 10)
        assert s.count("LOAD_BOOK") == 1  # never resent
    assert e.value.code == "INVALID_RATE"


async def test_book_already_booked():
    async with run_fake_tms(lambda req: Reply(b"ERR|CODE:ALREADY_BOOKED|MSG:taken\r\n")) as s:
        res = await _cmds(s.port).load_book("LD00271", "872144", 1900)
        assert s.count("LOAD_BOOK") == 1
    assert res.status == "already_booked"


async def test_book_ambiguous_then_verify_shows_booked_never_resends():
    """Timeout on BOOK, but a verifying LOAD_GET shows the load no longer OPEN ->
    report booked (unconfirmed) and crucially NEVER send a second BOOK."""

    def handler(req):
        if req["cmd"] == "LOAD_BOOK":
            return Reply(behavior="timeout")  # ambiguous
        return Reply(GET_BOOKED)  # verify: now booked

    async with run_fake_tms(handler) as s:
        res = await _cmds(s.port).load_book("LD00271", "872144", 1900)
        assert s.count("LOAD_BOOK") == 1  # NO double-book
        assert s.count("LOAD_GET") >= 1
    assert res.status == "booked" and res.confirmed is False


async def test_book_ambiguous_then_open_resends_exactly_once():
    """Timeout on BOOK, verify shows still OPEN -> exactly ONE resend, then success."""
    state = {"book": 0}

    def handler(req):
        if req["cmd"] == "LOAD_BOOK":
            state["book"] += 1
            return Reply(behavior="timeout") if state["book"] == 1 else Reply(BOOK_OK)
        return Reply(LD271)  # verify: still OPEN

    async with run_fake_tms(handler) as s:
        res = await _cmds(s.port).load_book("LD00271", "872144", 1900)
        assert s.count("LOAD_BOOK") == 2  # exactly one resend after the verify
    assert res.status == "booked"
