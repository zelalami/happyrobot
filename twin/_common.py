"""Shared bootstrap for the twin/ scripts.

Reuses the Public API client (workflow/hrlib.py) and its credentials
(workflow/.env) so the Twin data-layer tooling has a single source of auth and
zero install steps. Import this first in every twin/ script.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "workflow"
if str(_WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKFLOW_DIR))

from hrlib import HR, HRError, client_from_env, load_env  # noqa: E402

OUT = Path(__file__).resolve().parent / "discovery"


def dump(name: str, obj) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def as_list(body, *keys):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("data", "items", "results", "integrations", "events", "rows", *keys):
            if isinstance(body.get(k), list):
                return body[k]
    return []


__all__ = ["HR", "HRError", "client_from_env", "load_env", "dump", "as_list", "OUT"]
