"""
JSON result reporter.

Writes timestamped result files to tests/results/.
Provides trend analysis across historical runs.
"""

import json
import statistics
from datetime import datetime
from pathlib import Path

from tests.performance.harness import RunMetrics
from tests.performance.scenarios import TestCase

RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Build result record
# ---------------------------------------------------------------------------

def build_test_record(case: TestCase, runs: list[RunMetrics]) -> dict:
    passed_runs = [r for r in runs if r.passed]
    reliability = len(passed_runs) / len(runs) if runs else 0.0

    durations = [r.duration for r in runs]
    latencies = [r.first_token_latency for r in runs if r.first_token_latency]
    corrections = [r.self_corrections for r in runs]

    return {
        "id": case.id,
        "name": case.name,
        "category": case.category,
        "tags": case.tags,
        "prompt": case.prompt,
        # Overall
        "passed": reliability == 1.0,
        "reliability": round(reliability, 3),
        "runs_total": len(runs),
        "runs_passed": len(passed_runs),
        # Timing
        "duration_avg": round(statistics.mean(durations), 3) if durations else None,
        "duration_min": round(min(durations), 3) if durations else None,
        "duration_max": round(max(durations), 3) if durations else None,
        "first_token_latency_avg": round(statistics.mean(latencies), 3) if latencies else None,
        # Tool use
        "total_tool_calls_avg": round(statistics.mean([r.total_tool_calls for r in runs]), 1),
        "execute_script_calls_avg": round(statistics.mean([r.execute_script_calls for r in runs]), 1),
        "self_corrections_avg": round(statistics.mean(corrections), 2),
        "rag_searches_avg": round(statistics.mean([r.rag_searches for r in runs]), 2),
        # Safety
        "interrupted": any(r.interrupted for r in runs),
        # Verifications (from first run)
        "verifications": runs[0].verifications if runs else {},
        "screenshot_ssim": _extract_ssim(runs[0]) if runs else None,
        # Errors
        "errors": [r.error for r in runs if r.error],
    }


def _extract_ssim(run: RunMetrics) -> float | None:
    sc = run.verifications.get("screenshot", {})
    return sc.get("ssim")


# ---------------------------------------------------------------------------
# Build full run record
# ---------------------------------------------------------------------------

def build_run_record(
    test_records: list[dict],
    model: str,
    provider: str,
    run_id: str,
) -> dict:
    total = len(test_records)
    passed = sum(1 for t in test_records if t["passed"])
    durations = [t["duration_avg"] for t in test_records if t["duration_avg"]]
    corrections = [t["self_corrections_avg"] for t in test_records]
    reliabilities = [t["reliability"] for t in test_records]
    ssims = [t["screenshot_ssim"] for t in test_records if t["screenshot_ssim"] is not None]

    by_category: dict[str, dict] = {}
    for t in test_records:
        cat = t["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passed": 0}
        by_category[cat]["total"] += 1
        if t["passed"]:
            by_category[cat]["passed"] += 1

    return {
        "run_id": run_id,
        "timestamp": run_id,
        "model": model,
        "provider": provider,
        # Summary
        "summary": {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 3) if total else 0,
            "avg_duration_seconds": round(statistics.mean(durations), 2) if durations else None,
            "avg_self_corrections": round(statistics.mean(corrections), 2) if corrections else None,
            "avg_reliability": round(statistics.mean(reliabilities), 3) if reliabilities else None,
            "avg_screenshot_ssim": round(statistics.mean(ssims), 4) if ssims else None,
            "by_category": {
                cat: {
                    "pass_rate": round(v["passed"] / v["total"], 3),
                    "passed": v["passed"],
                    "total": v["total"],
                }
                for cat, v in by_category.items()
            },
        },
        "tests": test_records,
    }


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

def save_result(record: dict) -> Path:
    filename = f"{record['run_id'].replace(':', '-').replace(' ', '_')}.json"
    path = RESULTS_DIR / filename
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    return path


def load_all_results() -> list[dict]:
    results = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            with open(path) as f:
                results.append(json.load(f))
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def print_trend(n: int = 5) -> None:
    """Print a summary of the last N runs showing improvement/regression."""
    results = load_all_results()[-n:]
    if not results:
        print("No historical results found.")
        return

    print(f"\n{'Run':<26} {'Model':<24} {'Pass%':>6} {'Avg s':>7} {'Corr':>5} {'SSIM':>6}")
    print("-" * 75)
    for r in results:
        s = r["summary"]
        print(
            f"{r['timestamp']:<26} "
            f"{r['model']:<24} "
            f"{s['pass_rate']*100:>5.1f}% "
            f"{(s['avg_duration_seconds'] or 0):>7.1f} "
            f"{(s['avg_self_corrections'] or 0):>5.2f} "
            f"{(s['avg_screenshot_ssim'] or 0):>6.3f}"
        )

    if len(results) >= 2:
        prev = results[-2]["summary"]
        curr = results[-1]["summary"]
        delta = (curr["pass_rate"] - prev["pass_rate"]) * 100
        arrow = "+" if delta >= 0 else ""
        print(f"\nPass rate vs previous run: {arrow}{delta:.1f}%")


# ---------------------------------------------------------------------------
# Console report
# ---------------------------------------------------------------------------

def print_run_summary(record: dict) -> None:
    s = record["summary"]
    print(f"\n{'='*60}")
    print(f"Run: {record['run_id']}")
    print(f"Model: {record['provider']}/{record['model']}")
    print(f"{'='*60}")
    print(f"  Tests:         {s['passed']}/{s['total_tests']} passed ({s['pass_rate']*100:.1f}%)")
    print(f"  Avg duration:  {s['avg_duration_seconds']:.1f}s")
    print(f"  Self-correct:  {s['avg_self_corrections']:.2f} avg per test")
    print(f"  Reliability:   {s['avg_reliability']*100:.1f}%")
    if s["avg_screenshot_ssim"]:
        print(f"  Screenshot SSIM: {s['avg_screenshot_ssim']:.3f}")

    print(f"\n  By category:")
    for cat, v in s["by_category"].items():
        bar = "#" * v["passed"] + "." * (v["total"] - v["passed"])
        print(f"    {cat:<20} [{bar}] {v['passed']}/{v['total']}")

    print(f"\n  {'ID':<10} {'Name':<38} {'Pass':>5} {'Time':>6} {'Corr':>5}")
    print(f"  {'-'*65}")
    for t in record["tests"]:
        mark = "PASS" if t["passed"] else "FAIL"
        dur = f"{t['duration_avg']:.1f}s" if t["duration_avg"] else "  -  "
        corr = f"{t['self_corrections_avg']:.1f}"
        print(f"  {t['id']:<10} {t['name']:<38} {mark:>5} {dur:>6} {corr:>5}")

    print()
