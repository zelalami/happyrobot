"""In-process fake TMS for client/command tests.

A raw-asyncio TCP server that reads one request frame per connection and replies
according to a handler the test supplies. The handler returns a `Reply` carrying
both the bytes and the SOCKET BEHAVIOUR, so we can reproduce each wire fault:

  normal  : write data, close                          -> clean response
  partial : write a prefix (no END), close             -> PARTIAL fault
  timeout : write nothing, wait for the client to close -> TIMEOUT fault
  delayed : write full data+END, then hold the socket open
            (the client must return on END, not wait for close)

Behaviours that "hold open" simply await the client's EOF instead of sleeping a
fixed time, so tests stay fast and leave no lingering timers.

`.requests` records every parsed request, so a test can assert exactly how many
LOAD_BOOK frames were sent (the no-double-book invariant).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class Reply:
    data: bytes = b""
    behavior: str = "normal"  # normal | partial | timeout | delayed


def parse_request(frame: bytes) -> dict:
    text = frame.decode("ascii", "replace").rstrip("\r\n")
    cmd = None
    fields: dict[str, str] = {}
    for tok in text.split("|"):
        k, _, v = tok.partition(":")
        if k == "CMD":
            cmd = v
        elif k == "AUTH" or not k:
            continue
        else:
            fields[k] = v
    return {"cmd": cmd, "fields": fields}


class FakeTMS:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[dict] = []
        self.host = "127.0.0.1"
        self.port: int | None = None
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            frame = await reader.readuntil(b"\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        self.requests.append(parse_request(frame))
        reply = self.handler(self.requests[-1])
        try:
            if reply.behavior == "timeout":
                await reader.read()  # send nothing; unblock when client gives up & closes
            elif reply.behavior == "partial":
                writer.write(reply.data)
                await writer.drain()
            elif reply.behavior == "delayed":
                writer.write(reply.data)
                await writer.drain()
                await reader.read()  # hold the socket open until the client closes
            else:  # normal
                writer.write(reply.data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def count(self, cmd: str) -> int:
        return sum(1 for r in self.requests if r["cmd"] == cmd)


@asynccontextmanager
async def run_fake_tms(handler):
    server = FakeTMS(handler)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()
