"""Thin, dependency-free HappyRobot Public API client for the workflow build.

Reads credentials from workflow/.env (git-ignored). Never prints secrets: the
bearer key is redacted from any diagnostic output. Uses urllib (stdlib) so the
workflow/ tooling has zero install steps.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env(path: Path = _ENV_PATH) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file (ignores blanks and # comments)."""
    env: dict[str, str] = {}
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Copy workflow/.env.example -> workflow/.env and fill it in."
        )
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    # Allow real-process env to override file values (handy for CI / one-offs).
    for k in ("HR_API_KEY", "HR_BASE_URL", "ADAPTER_API_KEY", "ADAPTER_BASE_URL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def redact(text: str, *secrets: str) -> str:
    out = text
    for s in secrets:
        if s and len(s) >= 6:
            out = out.replace(s, s[:6] + "…<redacted>")
    return out


class HRError(Exception):
    def __init__(self, status: int, body):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


class HR:
    """Minimal bearer-auth JSON client. .request returns (status, parsed_body)."""

    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self._key = api_key

    def request(self, method: str, path: str, body=None, raw: bool = False):
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        data = None
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = resp.read().decode()
                status = resp.status
        except urllib.error.HTTPError as e:
            payload = e.read().decode()
            status = e.code
        except urllib.error.URLError as e:
            raise SystemExit(f"Network error reaching {url}: {e.reason}")
        if raw:
            return status, payload
        try:
            parsed = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            parsed = payload
        return status, parsed

    def get(self, path: str, **kw):
        return self.request("GET", path, **kw)

    def post(self, path: str, body=None, **kw):
        return self.request("POST", path, body=body, **kw)

    def patch(self, path: str, body=None, **kw):
        return self.request("PATCH", path, body=body, **kw)

    def put(self, path: str, body=None, **kw):
        return self.request("PUT", path, body=body, **kw)

    def delete(self, path: str, **kw):
        return self.request("DELETE", path, **kw)


def client_from_env(env: dict[str, str] | None = None) -> HR:
    env = env or load_env()
    key = env.get("HR_API_KEY", "")
    if not key or key.startswith("hr_xxxx"):
        raise SystemExit("HR_API_KEY is not set in workflow/.env")
    return HR(env.get("HR_BASE_URL", "https://platform.happyrobot.ai/api/v2"), key)
