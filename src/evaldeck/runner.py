"""Run cases independently and compare compatible results by ID."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from . import __version__
from .checks import evaluate
from .providers import Provider, ProviderError
from .schema import Case, InputError, loads, nonempty_string


def summarize(cases: list[dict]) -> dict:
    return {"total": len(cases), **{status: sum(c["status"] == status for c in cases) for status in ("pass", "fail", "error")}}


def run(cases: list[Case], provider: Provider, *, label: str = "") -> dict[str, Any]:
    results = []
    for case in cases:
        started = time.perf_counter()
        result = {"id": case.id, "fingerprint": case.fingerprint, "prompt": case.prompt}
        try:
            completion = provider.complete(case)
            elapsed = (time.perf_counter() - started) * 1000
            checks = evaluate(completion.output, case.checks)
            result.update(status="pass" if all(c["passed"] for c in checks) else "fail",
                          output=completion.output, checks=checks, usage=completion.usage,
                          latency_ms=round(elapsed, 3), error=None)
        except ProviderError as error:
            result.update(status="error", output=None, checks=[], usage=None,
                          latency_ms=round((time.perf_counter() - started) * 1000, 3), error=str(error))
        results.append(result)
    dataset = json.dumps(sorted((c.id, c.fingerprint) for c in cases), separators=(",", ":"))
    return {
        "schema_version": 1, "evaldeck_version": __version__,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": label, "provider": provider.name, "model": provider.model,
        "dataset_fingerprint": hashlib.sha256(dataset.encode()).hexdigest(),
        "latency_note": "local replay lookup time, not model inference" if provider.name == "replay" else "observed request latency; includes network and response decoding",
        "usage_source": "fixture" if provider.name == "replay" else "provider-reported",
        "summary": summarize(results), "cases": results,
    }


def load_report(path: Path) -> dict:
    try:
        report = loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, InputError) as error:
        raise InputError(f"cannot read report {path}: {error}") from error
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise InputError(f"{path}: unsupported report schema")
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise InputError(f"{path}: report has no cases")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not nonempty_string(case.get("id")):
            raise InputError(f"{path}: invalid case id")
        if case["id"] in seen:
            raise InputError(f"{path}: duplicate case id {case['id']!r}")
        seen.add(case["id"])
        if case.get("status") not in ("pass", "fail", "error"):
            raise InputError(f"{path}: invalid case status")
        fingerprint = case.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise InputError(f"{path}: missing or invalid case fingerprint")
        checks = case.get("checks")
        if not isinstance(checks, list) or any(not isinstance(c, dict) or type(c.get("passed")) is not bool for c in checks):
            raise InputError(f"{path}: invalid check results")
        if case["status"] == "pass" and (not checks or not all(c["passed"] for c in checks)):
            raise InputError(f"{path}: pass status conflicts with check results")
        if case["status"] == "fail" and (not checks or all(c["passed"] for c in checks)):
            raise InputError(f"{path}: fail status conflicts with check results")
    if report.get("summary") != summarize(cases):
        raise InputError(f"{path}: summary conflicts with case results")
    return report


def compare(baseline: dict, current: dict) -> dict:
    before = {case["id"]: case for case in baseline["cases"]}
    after = {case["id"]: case for case in current["cases"]}
    common = before.keys() & after.keys()
    changed = sorted(case_id for case_id in common if before[case_id]["fingerprint"] != after[case_id]["fingerprint"])
    if changed:
        raise InputError(f"cannot compare changed prompts/checks for case IDs: {changed}; create a reviewed new baseline")
    removed = sorted(before.keys() - after.keys())
    regressed = sorted(case_id for case_id in common if before[case_id]["status"] == "pass" and after[case_id]["status"] != "pass")
    return {
        "regressions": regressed,
        "improvements": sorted(case_id for case_id in common if before[case_id]["status"] != "pass" and after[case_id]["status"] == "pass"),
        "added": sorted(after.keys() - before.keys()),
        "removed": removed,
        "unchanged": sorted(case_id for case_id in common if before[case_id]["status"] == after[case_id]["status"]),
        "has_regressions": bool(regressed or removed),
    }


def exit_code(report: dict, comparison: dict | None = None) -> int:
    if comparison and comparison["has_regressions"]:
        return 3
    return 1 if report["summary"]["fail"] or report["summary"]["error"] else 0
