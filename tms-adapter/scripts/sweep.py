#!/usr/bin/env python3
"""TMS data-discovery sweep.

Probes the legacy TMS to answer four questions before we build the adapter:
  1. Does this token return live loads, and on which lanes?
  2. Does LOAD_GET expose MAX_BUY (the hidden ceiling) on this token?
  3. Are RATE / MAX_BUY in dollars or cents?
  4. What are the fixed-width column widths? (raw transcripts are saved to measure)

Read-only: sends DEBUG_ECHO, LOAD_QUERY, LOAD_GET only — never LOAD_BOOK.
Never prints the auth token or request frames (responses carry no token).

Run:  cd tms-adapter && python3 scripts/sweep.py
"""

import os
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = HERE.parent
TRANSCRIPTS = ADAPTER_ROOT / "tests" / "fixtures" / "transcripts"

CONNECT_TIMEOUT = 4.0
READ_TIMEOUT = 6.0
MAX_ATTEMPTS = 3          # retry transient TMS faults (timeout/partial/malformed)
MAX_FRAME = 4096

US_STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
             "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
             "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
             "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
             "VT", "VA", "WA", "WV", "WI", "WY", "DC"]

EQUIPMENT = ["DRY_VAN", "REEFER", "FLATBED", "STEP_DECK", "POWER_ONLY", "HOTSHOT"]


def load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_config():
    load_dotenv(ADAPTER_ROOT / ".env")
    host = os.environ.get("TMS_HOST")
    port = os.environ.get("TMS_PORT")
    token = os.environ.get("TMS_TOKEN")
    print(f"token loaded: {'yes' if token else 'MISSING'}")
    missing = [n for n, v in (("TMS_HOST", host), ("TMS_PORT", port), ("TMS_TOKEN", token)) if not v]
    if missing:
        sys.exit(f"Missing config: {', '.join(missing)} — set them in tms-adapter/.env")
    return host, int(port), token


def encode(cmd, token, fields):
    pairs = [f"CMD:{cmd}", f"AUTH:{token}"]
    for k, v in fields.items():
        v = str(v)
        if any(c in v for c in ("|", "\r", "\n")):
            raise ValueError(f"illegal char in field {k}")
        pairs.append(f"{k}:{v}")
    frame = ("|".join(pairs) + "\r\n").encode("ascii")
    if len(frame) > MAX_FRAME:
        raise ValueError("frame exceeds 4096B")
    return frame


def _terminal(buf):
    lines = buf.split(b"\r\n")
    if any(ln == b"END" for ln in lines):
        return "ok"
    if lines and lines[0].startswith(b"ERR|") and len(lines) >= 2:
        return "err"
    return None


def exchange(host, port, frame):
    """One request per connection. Returns (raw_bytes, status)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        sock.connect((host, port))
        sock.settimeout(READ_TIMEOUT)
        sock.sendall(frame)
        buf = bytearray()
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                return bytes(buf), "timeout"
            if not chunk:                       # peer closed (EOF)
                return bytes(buf), (_terminal(buf) or "partial")
            buf += chunk
            status = _terminal(buf)
            if status:
                return bytes(buf), status
            if len(buf) > MAX_FRAME * 8:
                return bytes(buf), "malformed"
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return b"", f"conn_error:{e.__class__.__name__}"
    finally:
        sock.close()


def query(host, port, token, cmd, fields):
    """Read command with bounded retries on transient faults."""
    last = (b"", "unknown")
    for _ in range(MAX_ATTEMPTS):
        raw, status = exchange(host, port, encode(cmd, token, fields))
        if status in ("ok", "err"):
            return raw, status
        last = (raw, status)
    return last


def parse_records(raw):
    """Return (records, error_line). Padded values are kept verbatim (for width measuring)."""
    records, error = [], None
    for line in raw.split(b"\r\n"):
        if not line or line == b"END":
            continue
        s = line.decode("ascii", "replace")
        if s.startswith("ERR|"):
            error = s
            continue
        rec = {}
        for tok in s.split("|"):
            if ":" in tok:
                k, _, v = tok.partition(":")
                rec[k] = v
        if rec:
            records.append(rec)
    return records, error


def main():
    host, port, token = get_config()
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    out = []

    def say(line=""):
        print(line)
        out.append(line)

    say(f"TMS {host}:{port}")
    say()

    # [1] connectivity + encoder check (DEBUG_ECHO bypasses fault injection)
    raw, status = query(host, port, token, "DEBUG_ECHO", {"MSG": "HELLO"})
    text = raw.decode("ascii", "replace")
    if status != "ok" or "AUTH:OK" not in text:
        sys.exit(f"DEBUG_ECHO failed (status={status}): {text!r}\nFix token/host before sweeping.")
    fp = next((l.split("FIELDS_PARSED:")[1].split("|")[0]
               for l in text.split("\r\n") if "FIELDS_PARSED:" in l), "?")
    say(f"[1] DEBUG_ECHO ok — AUTH:OK, FIELDS_PARSED={fp} (expect 3: CMD+AUTH+MSG)")
    say()

    # [2] sweep origin states — broadest net (no equipment filter)
    say("[2] Sweeping origin states for live loads...")
    found, lanes = {}, []
    for st in US_STATES:
        raw, status = query(host, port, token, "LOAD_QUERY", {"ORIG_STATE": st, "MAX_RESULTS": 25})
        recs, err = parse_records(raw)
        if status == "ok" and recs:
            lanes.append((st, len(recs)))
            (TRANSCRIPTS / f"query_orig_{st}.txt").write_bytes(raw)
            for r in recs:
                lid = (r.get("LOAD_ID") or "").strip()   # IDs are space-padded to width 12; strip before reuse
                if lid:
                    found.setdefault(lid, r)
            say(f"    {st}: {len(recs)} load(s)")
        elif status == "err":
            say(f"    {st}: {err}")
    if not lanes:
        say("    (no loads on any origin-state query)")
    say()

    # [3] equipment vocabulary check
    say("[3] Equipment-type filter check...")
    for eq in EQUIPMENT:
        raw, status = query(host, port, token, "LOAD_QUERY", {"EQTYPE": eq, "MAX_RESULTS": 5})
        recs, _ = parse_records(raw)
        say(f"    {eq}: {len(recs) if recs else 'none'}")
    say()

    if not found:
        say("NO-GO so far: no loads discovered. Faults are transient — re-run once or twice;")
        say("if still empty, ask your interview contact whether this token has seeded loads.")
        (TRANSCRIPTS / "SWEEP_SUMMARY.md").write_text("\n".join(out) + "\n")
        return

    # [4] LOAD_GET sample -> confirm MAX_BUY presence + units + widths
    say(f"[4] Full record for up to 5 of {len(found)} unique loads...")
    say()
    saw_max_buy = False
    for lid in list(found)[:5]:
        raw, status = query(host, port, token, "LOAD_GET", {"LOAD_ID": lid})
        recs, err = parse_records(raw)
        if status != "ok" or not recs:
            say(f"    {lid}: LOAD_GET {status} {err or ''}")
            continue
        (TRANSCRIPTS / f"loadget_{lid}.txt").write_bytes(raw)
        rec = recs[0]
        rate, miles = rec.get("RATE", "").strip(), rec.get("MILES", "").strip()
        has_mb = "MAX_BUY" in rec
        saw_max_buy = saw_max_buy or has_mb
        lane = (f'{rec.get("ORIG_CITY","?").strip()},{rec.get("ORIG_STATE","?")} -> '
                f'{rec.get("DEST_CITY","?").strip()},{rec.get("DEST_STATE","?")}')
        say(f"    {lid}  {lane}  EQ={rec.get('EQTYPE','?').strip()}  STATUS={rec.get('STATUS','?').strip()}")
        say(f"        RATE={rate!r}  MAX_BUY={'(ABSENT)' if not has_mb else repr(rec['MAX_BUY'].strip())}  MILES={miles!r}")
        try:
            ri, mi = int(rate), int(miles)
            if mi:
                say(f"        $/mile if dollars: {ri/mi:.2f}   if cents: {ri/100/mi:.2f}   (freight ~ $1.5-4.5/mi)")
        except ValueError:
            pass
        widths = "  ".join(f"{k}={len(v)}" for k, v in rec.items())
        say(f"        on-wire widths: {widths}")
        say()

    # [5] verdict
    say("=" * 64)
    if saw_max_buy:
        say("GO: MAX_BUY is present — the ceiling can be read from the TMS.")
    else:
        say("NO-GO on ceiling: MAX_BUY is ABSENT on every sampled load.")
        say("  -> Email your interview contact for a MAX_BUY-flagged token NOW (lead time).")
        say("  -> Until then the ceiling can only come from a documented env fallback.")
    say(f"Live lanes: {', '.join(f'{s}({n})' for s, n in lanes) or 'none'}")
    say(f"Raw transcripts: {TRANSCRIPTS}")
    (TRANSCRIPTS / "SWEEP_SUMMARY.md").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
