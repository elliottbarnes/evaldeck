"""Small deterministic checks. No model judges, code evaluation, or regex execution."""

from __future__ import annotations

import json
from typing import Any

from .schema import InputError, loads, number


def _pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isascii() and token.isdigit():
            if (token != "0" and token.startswith("0")) or len(token) > len(str(len(value))) or int(token) >= len(value):
                raise KeyError(pointer)
            value = value[int(token)]
        else:
            raise KeyError(pointer)
    return value


def _equal(actual: Any, expected: Any) -> bool:
    # Python equates True and 1; a JSON contract should not.
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def evaluate(output: str, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    parsed: Any = None
    json_error = None
    try:
        parsed = loads(output)
    except InputError as error:
        json_error = str(error)
    for check in checks:
        kind = check["type"]
        needs_json = kind in ("json", "required_keys", "number_range") or "path" in check
        passed = False
        if needs_json and json_error is not None:
            detail = f"invalid JSON: {json_error}"
        else:
            try:
                actual = _pointer(parsed, check.get("path", "")) if needs_json else output
                if kind == "json":
                    passed, detail = True, "valid JSON"
                elif kind == "required_keys":
                    missing = [key for key in check["keys"] if not isinstance(actual, dict) or key not in actual]
                    passed = isinstance(actual, dict) and not missing
                    detail = "required keys present" if passed else f"missing keys or not an object: {missing}"
                elif kind == "equals":
                    passed = _equal(actual, check["value"])
                    detail = "values match" if passed else f"expected {json.dumps(check['value'], ensure_ascii=False)}, got {json.dumps(actual, ensure_ascii=False)}"
                elif kind == "contains":
                    passed = isinstance(actual, str) and check["value"] in actual
                    detail = "substring present" if passed else f"expected text containing {check['value']!r}"
                elif kind == "number_range":
                    passed = number(actual) and check.get("min", float("-inf")) <= actual <= check.get("max", float("inf"))
                    detail = "number in inclusive range" if passed else f"expected number in [{check.get('min', '-∞')}, {check.get('max', '∞')}], got {actual!r}"
                else:
                    raise ValueError(f"unsupported validated check: {kind}")
            except KeyError:
                detail = f"JSON path not found: {check.get('path')!r}"
        results.append({"check": check, "passed": passed, "detail": detail})
    return results
