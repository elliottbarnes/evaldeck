"""The CLI has no network behavior unless --live is explicitly selected."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

from . import __version__
from .providers import ChatHTTPProvider, ReplayProvider
from .report import write_report
from .runner import compare, exit_code, load_report, run
from .schema import InputError, load_cases


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Replay-first contract evaluations for AI outputs.")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("run", help="evaluate a dataset and write JSON + HTML reports")
    evaluate.add_argument("dataset", type=Path, help="UTF-8 JSONL evaluation cases")
    providers = evaluate.add_mutually_exclusive_group(required=True)
    providers.add_argument("--replay", type=Path, metavar="FIXTURES", help="run free, offline output fixtures")
    providers.add_argument("--live", action="store_true", help="send prompts to EVALDECK_API_URL; may incur costs")
    evaluate.add_argument("--out", type=Path, default=Path("reports/latest"), help="output directory (default: reports/latest)")
    evaluate.add_argument("--baseline", type=Path, help="earlier report.json to compare by case ID")
    evaluate.add_argument("--label", default="", help="human-readable report title")
    evaluate.add_argument("--timeout", type=positive_float, default=30, help="live socket timeout in seconds (default: 30)")
    evaluate.add_argument("--max-tokens", type=positive_int, default=512, help="live max_completion_tokens (default: 512)")
    validate = commands.add_parser("validate", help="validate dataset and optional replay fixture IDs; no network")
    validate.add_argument("dataset", type=Path)
    validate.add_argument("--replay", type=Path)
    difference = commands.add_parser("compare", help="compare two existing reports; no network")
    difference.add_argument("baseline", type=Path)
    difference.add_argument("current", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            current = load_report(args.current)
            comparison = compare(load_report(args.baseline), current)
            print(json.dumps(comparison, indent=2))
            return exit_code(current, comparison)
        cases = load_cases(args.dataset)
        if args.command == "validate":
            if args.replay:
                ReplayProvider(args.replay, cases)
            print(f"Valid: {len(cases)} cases" + ("; replay fixture IDs match" if args.replay else ""))
            return 0
        baseline = load_report(args.baseline) if args.baseline else None
        if baseline:
            # Reject changed checks before making any potentially billable requests.
            compare(baseline, {"cases": [{"id": c.id, "fingerprint": c.fingerprint, "status": "pass"} for c in cases]})
        inputs = [args.dataset, args.replay, args.baseline]
        destinations = {(args.out / name).resolve() for name in ("report.json", "report.html")}
        if any(path and path.resolve() in destinations for path in inputs):
            raise InputError("output would overwrite an input or baseline; choose a different --out directory")
        provider = ReplayProvider(args.replay, cases) if args.replay else ChatHTTPProvider(timeout=args.timeout, max_tokens=args.max_tokens)
        report = run(cases, provider, label=args.label)
        comparison = compare(baseline, report) if baseline else None
        if comparison:
            report["comparison"] = comparison
        json_path, html_path = write_report(report, args.out)
        counts = report["summary"]
        print(f"{counts['total']} cases · {counts['pass']} pass · {counts['fail']} fail · {counts['error']} error")
        if comparison:
            print(f"Regressions: {comparison['regressions']}; removed: {comparison['removed']}; improvements: {comparison['improvements']}")
        print(f"JSON: {json_path}\nHTML: {html_path}")
        return exit_code(report, comparison)
    except (InputError, OSError) as error:
        print(f"evaldeck: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
