"""
CLI entry point for the performance test suite.

Usage:
    # Run all tests
    python -m tests.performance.runner

    # Run only smoke tests
    python -m tests.performance.runner --tags smoke

    # Run specific test IDs
    python -m tests.performance.runner --ids BG-001 BG-002

    # Run against a specific provider/model
    python -m tests.performance.runner --provider anthropic --model claude-haiku-4-5-20251001

    # Show trend from last N runs
    python -m tests.performance.runner --trend 5

    # Skip reliability runs (run each test once)
    python -m tests.performance.runner --no-reliability
"""

import argparse
import sys
from datetime import datetime, timezone

from agent.config import UserConfig, load_config
from tests.performance.harness import run_test, run_test_with_reliability
from tests.performance.reporter import (
    build_run_record,
    build_test_record,
    print_run_summary,
    print_trend,
    save_result,
)
from tests.performance.scenarios import get_scenarios


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FreeCAD agent performance test runner")
    p.add_argument("--tags", nargs="+", help="Filter by tags (e.g. smoke safety)")
    p.add_argument("--ids", nargs="+", help="Run specific test IDs (e.g. BG-001 MD-003)")
    p.add_argument("--provider", help="Override provider (anthropic/openai/google/ollama)")
    p.add_argument("--model", help="Override model name")
    p.add_argument("--api-key", help="Override API key")
    p.add_argument("--host", default="127.0.0.1", help="FreeCAD host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=65432, help="FreeCAD port (default: 65432)")
    p.add_argument("--trend", type=int, metavar="N", help="Show trend from last N runs and exit")
    p.add_argument("--no-reliability", action="store_true", help="Run each test once (skip reliability runs)")
    p.add_argument("--output", help="Save result JSON to this path (default: tests/results/<timestamp>.json)")
    return p.parse_args()


def build_config(args: argparse.Namespace) -> UserConfig:
    config = load_config()
    if args.provider:
        config.provider = args.provider
    if args.model:
        config.model = args.model
    if args.api_key:
        config.api_key = args.api_key
    config.freecad_host = args.host
    config.freecad_port = args.port
    return config


def main() -> int:
    args = parse_args()

    # --trend mode: just print history and exit
    if args.trend:
        print_trend(args.trend)
        return 0

    config = build_config(args)
    scenarios = get_scenarios(tags=args.tags, ids=args.ids)

    if not scenarios:
        print("No scenarios matched the given filters.")
        return 1

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\nFreeCAD Agent Performance Suite")
    print(f"Run ID  : {run_id}")
    print(f"Model   : {config.provider}/{config.model}")
    print(f"FreeCAD : {config.freecad_host}:{config.freecad_port}")
    print(f"Tests   : {len(scenarios)}")
    print()

    test_records = []
    failed_count = 0

    for i, case in enumerate(scenarios, 1):
        tag_str = f" [{', '.join(case.tags)}]" if case.tags else ""
        print(f"[{i}/{len(scenarios)}] {case.id} — {case.name}{tag_str}")

        if args.no_reliability:
            runs = [run_test(case, config)]
        else:
            runs = run_test_with_reliability(case, config)

        record = build_test_record(case, runs)
        test_records.append(record)

        # One-line result
        status = "PASS" if record["passed"] else "FAIL"
        dur = f"{record['duration_avg']:.1f}s" if record["duration_avg"] else "  -  "
        rel = f"{record['reliability']*100:.0f}%" if not args.no_reliability else ""
        corr = f"corr={record['self_corrections_avg']:.1f}"
        rag = f"rag={record['rag_searches_avg']:.1f}"
        errors = f" ERR: {record['errors'][0][:60]}" if record["errors"] else ""
        print(f"  -> {status}  {dur}  {rel}  {corr}  {rag}{errors}")

        if not record["passed"]:
            failed_count += 1
            for check_name, v in record["verifications"].items():
                if not v["passed"]:
                    print(f"     [FAIL] {check_name}: {v['detail']}")

    # Build and save full run record
    run_record = build_run_record(test_records, config.model, config.provider, run_id)
    result_path = save_result(run_record)

    print_run_summary(run_record)
    print(f"Results saved to: {result_path}")

    # Show delta vs previous run
    print_trend(2)

    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
