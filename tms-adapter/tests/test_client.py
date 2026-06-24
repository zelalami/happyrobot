from pathlib import Path

import pytest

from app.tms.client import TMSClient
from app.tms.faults import TMSFault, TMSFaultError
from app.tms.framing import decode_response
from fake_tms.server import FakeTMS, Reply, run_fake_tms

TRANSCRIPTS = Path(__file__).resolve().parent / "fixtures" / "transcripts"
LD271 = (TRANSCRIPTS / "loadget_LD00271.txt").read_bytes()


def _client(port: int, **kw) -> TMSClient:
    opts = dict(deadline_s=0.4, connect_timeout_s=0.3, read_timeout_s=0.3)
    opts.update(kw)
    return TMSClient("127.0.0.1", port, "T", **opts)


async def test_clean_exchange_returns_decodable_bytes():
    async with run_fake_tms(lambda req: Reply(LD271)) as s:
        raw = await _client(s.port).request("LOAD_GET", {"LOAD_ID": "LD00271"})
    assert decode_response(raw).records[0]["LOAD_ID"] == "LD00271"
    assert s.requests[0]["cmd"] == "LOAD_GET"
    assert s.requests[0]["fields"]["LOAD_ID"] == "LD00271"


async def test_timeout_fault():
    async with run_fake_tms(lambda req: Reply(behavior="timeout")) as s:
        with pytest.raises(TMSFaultError) as e:
            await _client(s.port).request("LOAD_GET", {"LOAD_ID": "X"})
    assert e.value.fault is TMSFault.TIMEOUT


async def test_partial_fault_is_discarded():
    prefix = LD271.split(b"END")[0]  # record line + CRLF, but no END terminator
    async with run_fake_tms(lambda req: Reply(prefix, "partial")) as s:
        with pytest.raises(TMSFaultError) as e:
            await _client(s.port).request("LOAD_GET", {"LOAD_ID": "X"})
    assert e.value.fault is TMSFault.PARTIAL


async def test_delayed_termination_is_success():
    # Server sends full response + END then holds the socket open. The client must
    # return on END; if it waited for close it would blow the 0.4s deadline -> TIMEOUT.
    async with run_fake_tms(lambda req: Reply(LD271, "delayed")) as s:
        raw = await _client(s.port).request("LOAD_GET", {"LOAD_ID": "X"})
    assert decode_response(raw).records[0]["LOAD_ID"] == "LD00271"


async def test_oversize_response_is_malformed():
    big = b"X" * 500  # no terminal, exceeds the tiny cap below
    async with run_fake_tms(lambda req: Reply(big, "partial")) as s:
        with pytest.raises(TMSFaultError) as e:
            await _client(s.port, max_response_bytes=100).request("LOAD_GET", {"LOAD_ID": "X"})
    assert e.value.fault is TMSFault.MALFORMED


async def test_connect_error_when_nothing_listening():
    s = FakeTMS(lambda req: Reply())
    await s.start()
    port = s.port
    await s.stop()  # port is now closed -> connection refused
    with pytest.raises(TMSFaultError) as e:
        await _client(port).request("LOAD_GET", {"LOAD_ID": "X"})
    assert e.value.fault in (TMSFault.CONNECT_ERROR, TMSFault.TIMEOUT)
