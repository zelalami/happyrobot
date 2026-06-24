"""Shared fixtures for router tests: a TestClient over an app wired with fakes."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.deps import get_commands, get_fmcsa, get_sms
from app.main import create_app
from app.services.fmcsa import StubFMCSAClient
from app.services.sms import StubSmsSender
from app.tms.framing import decode_response

TRANSCRIPTS = Path(__file__).resolve().parent / "fixtures" / "transcripts"

# Real normalized records (exactly what the live wire decodes to).
LD271 = decode_response((TRANSCRIPTS / "loadget_LD00271.txt").read_bytes()).records[0]
QUERY_AL = decode_response((TRANSCRIPTS / "query_orig_AL.txt").read_bytes()).records


class FakeCommands:
    """Stand-in for TMSCommands; returns canned records or raises a given exception."""

    def __init__(self, *, query=None, get=None, query_exc=None, get_exc=None,
                 echo=None, book=None, book_exc=None):
        self._query, self._get = query, get
        self._query_exc, self._get_exc = query_exc, get_exc
        self._book, self._book_exc = book, book_exc
        self._echo = echo if echo is not None else {"auth_ok": True, "fields_parsed": 3}
        self.book_calls = 0

    async def load_query(self, **filters):
        if self._query_exc:
            raise self._query_exc
        return self._query or []

    async def load_get(self, load_id):
        if self._get_exc:
            raise self._get_exc
        return self._get

    async def load_book(self, load_id, mc_number, agreed_rate):
        self.book_calls += 1
        if self._book_exc:
            raise self._book_exc
        return self._book

    async def debug_echo(self, msg="HELLO"):
        return self._echo


def make_client(commands=None, *, settings=None, adapter_api_key=None, fmcsa=None) -> TestClient:
    settings = settings or Settings(
        _env_file=None, tms_host="h", tms_port=1, tms_token="t",
        adapter_api_key=adapter_api_key, use_stubs=True,
    )
    app = create_app(settings)
    if commands is not None:
        app.dependency_overrides[get_commands] = lambda: commands
    app.dependency_overrides[get_fmcsa] = lambda: (fmcsa or StubFMCSAClient())
    sms = StubSmsSender()
    app.state._test_sms = sms                       # exposed for outbox assertions
    app.dependency_overrides[get_sms] = lambda: sms
    return TestClient(app)


@pytest.fixture
def client():
    return make_client(FakeCommands())
