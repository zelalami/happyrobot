"""Run the evals + adversarial suites against the live version, async, and
save raw results under qa/results/ for the report (qa/50_results.py renders them).

  - Custom evals: POST /custom-evals/{id}/run {version_id} -> run_id; poll the eval's
    /runs until the matching run carries a verdict (`passed` / `judge_reasoning`).
  - Adversarial suites: POST /generate -> poll generation_status -> POST /run ->
    poll the suite run -> fetch per-test verdicts (/test-runs).

Usage:
    python3 qa/40_run.py evals     # run all custom evals on the node
    python3 qa/40_run.py suites    # generate + run all adversarial suites
    python3 qa/40_run.py all       # both (default)

Writes qa/results/eval_runs.json and qa/results/suite_runs.json.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from qalib import PROMPT_NODE_ID, VERSION_ID, VOICE_AGENT_NODE_ID, client_from_env

RESULTS = pathlib.Path(__file__).resolve().parent / "results"


def _verdict_ready(r: dict) -> bool:
    return r.get("passed") is not None or bool(r.get("judge_reasoning"))


def run_evals(hr) -> list:
    s, b = hr.get(f"/nodes/{PROMPT_NODE_ID}/custom-evals")
    evals = sorted((b.get("data", []) if isinstance(b, dict) else []),
                   key=lambda e: e.get("name", ""))
    print(f"running {len(evals)} custom evals…")
    pending = {}  # eval_id -> (name, run_id)
    for ev in evals:
        s, rb = hr.post(f"/custom-evals/{ev['id']}/run", {"version_id": VERSION_ID})
        rid = rb.get("run_id") if isinstance(rb, dict) else None
        if rid:
            pending[ev["id"]] = (ev["name"], rid)
            print(f"  triggered {ev['name'][:55]:57} run={rid}")
        else:
            print(f"  FAILED to trigger {ev['name']!r} -> {s} {str(rb)[:160]}")

    results, waited = [], 0
    done = set()
    while len(done) < len(pending) and waited < 600:
        time.sleep(6); waited += 6
        for eid, (name, rid) in pending.items():
            if eid in done:
                continue
            s, rb = hr.get(f"/custom-evals/{eid}/runs?limit=10")
            runs = rb.get("runs", []) if isinstance(rb, dict) else []
            match = next((r for r in runs if r.get("id") == rid), None)
            if match and _verdict_ready(match):
                done.add(eid)
                results.append({"name": name, "eval_id": eid, "run_id": rid,
                                "passed": match.get("passed"),
                                "tool_calls_matched": match.get("tool_calls_matched"),
                                "actual_tool_calls": match.get("actual_tool_calls"),
                                "judge_reasoning": match.get("judge_reasoning"),
                                "output_messages": match.get("output_messages")})
                v = "PASS" if match.get("passed") else "FAIL"
                print(f"  [{v}] {name[:60]}  ({len(done)}/{len(pending)})")
    if len(done) < len(pending):
        print(f"  ! {len(pending) - len(done)} eval(s) did not finish within budget")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "eval_runs.json").write_text(json.dumps(results, indent=2))
    print(f"saved {len(results)} eval results -> qa/results/eval_runs.json")
    return results


def run_suites(hr) -> list:
    s, b = hr.get(f"/nodes/{VOICE_AGENT_NODE_ID}/adversarial-suites")
    suites = [x for x in (b.get("data", []) if isinstance(b, dict) else [])
              if x.get("name", "").startswith("ADV")]
    out = []
    for su in suites:
        sid, name = su["id"], su["name"]
        print(f"\n=== suite {name} ({sid}) ===")
        # 1) generate tests, poll generation to completion
        gs, gb = hr.post(f"/adversarial-suites/{sid}/generate", {"version_id": VERSION_ID})
        print(f"  generate -> {gs}")
        waited = 0
        status = su.get("generation_status")
        # Terminal generation states: "generated" (tests ready) is the success state.
        gen_done = ("generated", "completed", "complete", "ready")
        gen_bad = ("error", "failed")
        while waited < 300:
            s, gb = hr.get(f"/adversarial-suites/{sid}")
            status = (gb.get("suite", gb) if isinstance(gb, dict) else {}).get("generation_status")
            if status in gen_done or status in gen_bad:
                break
            time.sleep(5); waited += 5
        print(f"  generation_status={status}")
        if status in gen_bad:
            print("  generation failed; skipping run"); continue
        # 2) run the suite
        rs, rb = hr.post(f"/adversarial-suites/{sid}/run", {"version_id": VERSION_ID})
        srid = rb.get("suite_run_id") if isinstance(rb, dict) else None
        print(f"  run -> {rs} suite_run_id={srid}")
        if not srid:
            print(f"    {str(rb)[:200]}"); continue
        # 3) poll the suite run to terminal
        waited, run = 0, {}
        while waited < 600:
            s, rb = hr.get(f"/adversarial-suites/runs/{srid}")
            run = rb.get("run", rb) if isinstance(rb, dict) else {}
            st = str(run.get("status", "")).lower()
            tot, comp = run.get("total_tests"), run.get("completed_tests")
            if st in ("completed", "complete", "failed", "error", "cancelled") or (tot and comp == tot):
                break
            time.sleep(8); waited += 8
        # 4) per-test verdicts
        s, tb = hr.get(f"/adversarial-suites/runs/{srid}/test-runs")
        test_runs = tb.get("data") or tb.get("test_runs") or tb.get("runs") or [] if isinstance(tb, dict) else []
        print(f"  status={run.get('status')} total={run.get('total_tests')} "
              f"passed={run.get('passed_tests')} failed={run.get('failed_tests')}")
        out.append({"name": name, "suite_id": sid, "suite_run_id": srid,
                    "status": run.get("status"), "total_tests": run.get("total_tests"),
                    "passed_tests": run.get("passed_tests"), "failed_tests": run.get("failed_tests"),
                    "test_runs": test_runs})
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "suite_runs.json").write_text(json.dumps(out, indent=2))
    print(f"\nsaved {len(out)} suite results -> qa/results/suite_runs.json")
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    hr = client_from_env()
    if mode in ("evals", "all"):
        run_evals(hr)
    if mode in ("suites", "all"):
        run_suites(hr)


if __name__ == "__main__":
    main()
