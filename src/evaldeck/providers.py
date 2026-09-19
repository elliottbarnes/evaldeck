"""Replay fixtures and an explicit, bounded Chat Completions HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from http.client import HTTPException
import json
import os
from pathlib import Path
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .schema import Case, InputError, jsonl, loads, nonempty_string, only_keys

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ProviderError(RuntimeError):
    """A provider failed; remaining cases should still run."""


@dataclass(frozen=True)
class Completion:
    output: str
    usage: dict[str, int] | None = None


class Provider(Protocol):
    name: str
    model: str | None

    def complete(self, case: Case) -> Completion: ...


def _usage(value: Any, context: str) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InputError(f"{context}: usage must be an object")
    only_keys(value, {"input_tokens", "output_tokens", "total_tokens"}, context)
    if not value or any(type(count) is not int or count < 0 for count in value.values()):
        raise InputError(f"{context}: usage needs non-negative integer token counts")
    if all(key in value for key in ("input_tokens", "output_tokens", "total_tokens")):
        if value["input_tokens"] + value["output_tokens"] != value["total_tokens"]:
            raise InputError(f"{context}: usage total must equal input plus output tokens")
    return value


class ReplayProvider:
    name = "replay"
    model = None

    def __init__(self, path: Path, cases: list[Case]):
        self.fixtures: dict[str, Completion] = {}
        for line, record in jsonl(path):
            context = f"{path}:{line}"
            only_keys(record, {"id", "output", "usage"}, context)
            if not nonempty_string(record.get("id")) or not isinstance(record.get("output"), str):
                raise InputError(f"{context}: id must be non-empty and output must be a string")
            if record["id"] in self.fixtures:
                raise InputError(f"{context}: duplicate fixture id {record['id']!r}")
            self.fixtures[record["id"]] = Completion(record["output"], _usage(record.get("usage"), context))
        expected = {case.id for case in cases}
        actual = set(self.fixtures)
        if expected != actual:
            raise InputError(f"fixture ID mismatch; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")

    def complete(self, case: Case) -> Completion:
        return self.fixtures[case.id]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        # Never forward an Authorization header to a redirect target.
        return None


class ChatHTTPProvider:
    name = "chat-http"

    def __init__(self, *, timeout: float = 30, max_tokens: int = 512):
        self.url = os.environ.get("EVALDECK_API_URL", "")
        self.model = os.environ.get("EVALDECK_MODEL", "")
        self._key = os.environ.get("EVALDECK_API_KEY", "")
        try:
            parsed = urlsplit(self.url)
            parsed.port
        except ValueError:
            raise InputError("EVALDECK_API_URL is not a valid HTTPS endpoint") from None
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise InputError("EVALDECK_API_URL must be a full HTTPS endpoint without credentials, query, or fragment")
        if not nonempty_string(self.model) or not nonempty_string(self._key):
            raise InputError("live mode needs EVALDECK_MODEL and EVALDECK_API_KEY")
        if "\n" in self._key or "\r" in self._key:
            raise InputError("API key contains invalid header characters")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._opener = build_opener(_NoRedirect())

    def complete(self, case: Case) -> Completion:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": case.prompt}],
            "max_completion_tokens": self.max_tokens,
            "stream": False,
        }
        request = Request(self.url, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._key}",
            "User-Agent": "EvalDeck/0.1.0",
        }, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderError("provider response exceeded the 2 MiB limit")
            payload = loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ProviderError("provider returned an invalid response object")
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ProviderError("provider returned no completion choices")
            choice = choices[0]
            if choice.get("finish_reason") != "stop":
                raise ProviderError("provider did not finish normally (truncation, refusal, or unsupported output)")
            message = choice.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ProviderError("provider returned no text content")
            raw_usage = payload.get("usage")
            usage = None
            if raw_usage is not None:
                if not isinstance(raw_usage, dict):
                    raise ProviderError("provider returned invalid token usage")
                names = {"prompt_tokens": "input_tokens", "completion_tokens": "output_tokens", "total_tokens": "total_tokens"}
                normalized = {target: raw_usage[source] for source, target in names.items() if source in raw_usage}
                usage = _usage(normalized, "provider") if normalized else None
            return Completion(message["content"], usage)
        except HTTPError as error:
            # Bodies and URLs may echo prompts or credentials. Report status only.
            raise ProviderError(f"provider HTTP {error.code}; response body omitted") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("provider timed out") from None
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise ProviderError("provider timed out") from None
            raise ProviderError("provider connection failed") from None
        except (UnicodeError, InputError, OSError, ValueError, HTTPException):
            raise ProviderError("provider returned an invalid response or connection failed") from None
