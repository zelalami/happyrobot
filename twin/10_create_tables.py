"""Apply twin/schema.sql to the org's Twin database via the Public API.

Idempotent (CREATE TABLE/INDEX IF NOT EXISTS). Reproducible: the committed schema.sql
is the source of truth. Splits the file into individual statements (the /twin/sql
endpoint runs one statement per call) and posts each with light 429 backoff.

    python3 twin/10_create_tables.py            # apply schema.sql
    python3 twin/10_create_tables.py --verify   # apply, then SELECT count + columns
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from _common import client_from_env

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def statements(sql_text: str) -> list[str]:
    """Split into statements on ';', dropping comments and blanks."""
    out, buf = [], []
    for raw in sql_text.splitlines():
        line = raw.split("--", 1)[0]  # strip line comments (no string literals contain '--' here)
        buf.append(line)
        if ";" in line:
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def run_sql(hr, sql: str, *, retries: int = 5):
    for attempt in range(retries):
        s, body = hr.post("/twin/sql", {"sql": sql})
        if s != 429:
            return s, body
        time.sleep(20 * (attempt + 1))
    return s, body


def main() -> None:
    hr = client_from_env()
    verify = "--verify" in sys.argv

    stmts = statements(SCHEMA.read_text())
    print(f"Applying {len(stmts)} statement(s) from {SCHEMA.name}\n")
    for stmt in stmts:
        label = " ".join(stmt.split())[:70]
        s, body = run_sql(hr, stmt)
        cmd = body.get("command") if isinstance(body, dict) else None
        ok = s in (200, 201)
        print(f"  [{s}] {cmd or ''!s:9} {label}")
        if not ok:
            print("    ERROR:", str(body)[:300])
            sys.exit(1)

    if verify:
        s, body = run_sql(
            hr,
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'call_outcomes' ORDER BY ordinal_position",
        )
        rows = body.get("rows", []) if isinstance(body, dict) else []
        print(f"\nVerify [{s}] call_outcomes has {len(rows)} columns:")
        for r in rows:
            print(f"   - {r.get('column_name'):20} {r.get('data_type')}")

    print("\nDone.")


if __name__ == "__main__":
    main()
