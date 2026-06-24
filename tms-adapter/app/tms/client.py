"""Synchronous TCP client for the legacy TMS, wrapped for async callers.

One socket per request (the protocol mandates it), opened fresh and ALWAYS
closed. A hard wall-clock deadline bounds the whole exchange so a Timeout fault
(no bytes) and a Delayed-termination fault (socket held open after a complete
response) both resolve deterministically instead of hanging. The blocking core
is the proven data-discovery sweep loop, made strict and offloaded to the threadpool so
it never blocks the event loop (FastAPI/Starlette run sync work the same way).
"""
from __future__ import annotations

import socket
import time
from typing import Any

import anyio

from app.tms.faults import TMSFault, TMSFaultError, find_terminal
from app.tms.framing import encode_request

# Generous absolute cap: a valid multi-record LOAD_QUERY is many small
# CRLF lines and never approaches this — so it only trips on runaway garbage.
MAX_RESPONSE_BYTES = 256 * 1024


class TMSClient:
    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        *,
        deadline_s: float = 8.0,
        connect_timeout_s: float = 3.0,
        read_timeout_s: float = 6.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ):
        self.host = host
        self.port = int(port)
        self._token = token  # secret; never logged. Only used to build the frame.
        self.deadline_s = deadline_s
        self.connect_timeout_s = connect_timeout_s
        self.read_timeout_s = read_timeout_s
        self.max_response_bytes = max_response_bytes

    @classmethod
    def from_settings(cls, settings) -> "TMSClient":
        return cls(
            settings.tms_host,
            settings.tms_port,
            settings.tms_token.get_secret_value(),
            deadline_s=settings.tms_deadline_s,
            connect_timeout_s=settings.tms_connect_timeout_s,
            read_timeout_s=settings.tms_read_timeout_s,
        )

    async def request(self, cmd: str, fields: dict[str, Any] | None = None) -> bytes:
        """Encode + exchange one command. Returns raw response bytes or raises TMSFaultError."""
        frame = encode_request(cmd, self._token, fields)
        return await anyio.to_thread.run_sync(self._exchange_sync, frame)

    def _exchange_sync(self, frame: bytes) -> bytes:
        deadline = time.monotonic() + self.deadline_s
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout_s)
        try:
            try:
                sock.connect((self.host, self.port))
            except (socket.timeout, TimeoutError) as e:
                raise TMSFaultError(TMSFault.TIMEOUT, "connect timed out") from e
            except OSError as e:
                raise TMSFaultError(TMSFault.CONNECT_ERROR, f"connect: {type(e).__name__}") from e

            try:
                sock.sendall(frame)
            except OSError as e:
                raise TMSFaultError(TMSFault.CONNECT_ERROR, f"send: {type(e).__name__}") from e

            buf = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TMSFaultError(TMSFault.TIMEOUT, "deadline exceeded", bytes(buf))
                sock.settimeout(min(self.read_timeout_s, remaining))
                try:
                    chunk = sock.recv(4096)
                except (socket.timeout, TimeoutError) as e:
                    raise TMSFaultError(TMSFault.TIMEOUT, "read timed out", bytes(buf)) from e
                except OSError as e:
                    raise TMSFaultError(
                        TMSFault.CONNECT_ERROR, f"recv: {type(e).__name__}", bytes(buf)
                    ) from e
                if not chunk:  # peer closed (EOF)
                    if find_terminal(buf, at_eof=True):
                        return bytes(buf)
                    raise TMSFaultError(TMSFault.PARTIAL, "peer closed before terminal", bytes(buf))
                buf += chunk
                if find_terminal(buf):  # strict CRLF boundary -> return at once (handles delayed-term)
                    return bytes(buf)
                if len(buf) > self.max_response_bytes:
                    raise TMSFaultError(TMSFault.MALFORMED, "oversize response", bytes(buf))
        finally:
            sock.close()  # always close our side
