"""Push workflow/prompt.md to the Carrier Sales Prompt node.
Updates only prompt_md (greeting + model preserved). prompt.md is the repo's
source of truth for the agent's behavior + guardrails.
"""
from __future__ import annotations

from pathlib import Path

from buildlib import PROMPT_NODE_ID, VERSION_ID
from hrlib import client_from_env


def main():
    hr = client_from_env()
    prompt_md = Path(__file__).resolve().parent.joinpath("prompt.md").read_text()
    s, b = hr.put(f"/versions/{VERSION_ID}/nodes/{PROMPT_NODE_ID}",
                  {"type": "prompt", "prompt_md": prompt_md})
    print(f"PUT prompt_md ({len(prompt_md)} chars) -> {s}")
    if s not in (200, 201):
        import json
        print(json.dumps(b, indent=2)[:800])


if __name__ == "__main__":
    main()
