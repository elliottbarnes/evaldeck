"""Validate inputs before contacting a provider or writing a report."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


class InputError(ValueError):
    """An invalid dataset, fixture, configuration, or baseline."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise InputError(f"non-finite JSON number: {value}")


def loads(text: str) -> Any:
    """Strict JSON: reject duplicate keys, NaN, Infinity, and overflow."""
    try:
        value = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
        _finite_tree(value)
        return value
    except (ValueError, RecursionError) as error:
        raise InputError(str(error)) from error


def _finite_tree(value: Any, depth: int = 0) -> None:
    if depth > 128:
        raise InputError("JSON nesting exceeds the 128-level limit")
    if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise InputError("JSON contains an unpaired Unicode surrogate")
    if isinstance(value, float) and not math.isfinite(value):
        raise InputError("non-finite JSON number")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_tree(key, depth + 1)
            _finite_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item, depth + 1)


def number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def only_keys(value: dict, allowed: set[str], context: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise InputError(f"{context}: unknown fields: {', '.join(sorted(unknown))}")


def jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows = []
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    value = loads(line)
                    if not isinstance(value, dict):
                        raise InputError("expected a JSON object")
                except InputError as error:
                    raise InputError(f"{path}:{line_number}: {error}") from error
                rows.append((line_number, value))
    except (OSError, UnicodeError) as error:
        raise InputError(f"cannot read {path}: {error}") from error
    if not rows:
        raise InputError(f"{path}: no records")
    return rows


@dataclass(frozen=True)
class Case:
    id: str
    prompt: str
    checks: list[dict[str, Any]]

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {"prompt": self.prompt, "checks": self.checks},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def validate_check(check: Any, context: str) -> None:
    fields = {
        "json": {"type"},
        "required_keys": {"type", "keys", "path"},
        "equals": {"type", "value", "path"},
        "contains": {"type", "value", "path"},
        "number_range": {"type", "path", "min", "max"},
    }
    if not isinstance(check, dict) or not isinstance(check.get("type"), str):
        raise InputError(f"{context}: check needs a string type")
    kind = check["type"]
    if kind not in fields:
        raise InputError(f"{context}: unknown check type {kind!r}")
    only_keys(check, fields[kind], context)
    if "path" in check:
        path = check["path"]
        if not isinstance(path, str) or (path and not path.startswith("/")):
            raise InputError(f"{context}: path must be a JSON Pointer, e.g. /label")
        if re.search(r"~(?:[^01]|$)", path):
            raise InputError(f"{context}: invalid JSON Pointer escape")
    if kind in ("equals", "contains") and "value" not in check:
        raise InputError(f"{context}: {kind} needs value")
    if kind == "contains" and not nonempty_string(check["value"]):
        raise InputError(f"{context}: contains value must be a non-empty string")
    if kind == "equals" and "path" not in check and not isinstance(check["value"], str):
        raise InputError(f"{context}: text equals needs a string value; use path for JSON")
    if kind == "required_keys":
        keys = check.get("keys")
        if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
            raise InputError(f"{context}: keys must be a non-empty string array")
        if len(set(keys)) != len(keys):
            raise InputError(f"{context}: duplicate required keys")
    if kind == "number_range":
        if "path" not in check:
            raise InputError(f"{context}: number_range needs path (empty string means JSON root)")
        if "min" not in check and "max" not in check:
            raise InputError(f"{context}: number_range needs min or max")
        for bound in ("min", "max"):
            if bound in check and not number(check[bound]):
                raise InputError(f"{context}: {bound} must be a finite number")
        if check.get("min", -math.inf) > check.get("max", math.inf):
            raise InputError(f"{context}: min must not exceed max")


def load_cases(path: Path) -> list[Case]:
    cases = []
    seen = set()
    for line, record in jsonl(path):
        context = f"{path}:{line}"
        only_keys(record, {"id", "prompt", "checks"}, context)
        if not nonempty_string(record.get("id")) or not nonempty_string(record.get("prompt")):
            raise InputError(f"{context}: id and prompt must be non-empty strings")
        if record["id"] in seen:
            raise InputError(f"{context}: duplicate case id {record['id']!r}")
        checks = record.get("checks")
        if not isinstance(checks, list) or not checks:
            raise InputError(f"{context}: checks must be a non-empty array")
        for index, check in enumerate(checks):
            validate_check(check, f"{context}, check {index + 1}")
        cases.append(Case(record["id"], record["prompt"], checks))
        seen.add(record["id"])
    return cases
