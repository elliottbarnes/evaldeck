# EvalDeck

**Replay-first contract tests for AI outputs.** Catch a changed label, an invalid JSON response, or a number that quietly became a string—then inspect exactly what failed.

EvalDeck is a small Python CLI for teams experimenting with model prompts and structured outputs. Run saved responses without API keys, compare a candidate against a baseline by case ID, and open a portable HTML report. An optional HTTPS adapter supports text-only Chat Completions endpoints.

- Five deterministic checks: valid JSON, required keys, exact equality, substring, and numeric range.
- JSON Pointer paths for nested values, including arrays and escaped keys.
- Explicit pass, fail, and provider-error results, with per-check explanations.
- Baseline gates detect regressions and removed cases; changed prompts or checks require a reviewed baseline.
- Standalone HTML with escaped content, no JavaScript, no remote assets, and a JSON companion.
- Zero runtime or test dependencies. Python 3.11+.

## Try the offline demo

```sh
git clone https://github.com/elliottbarnes/evaldeck.git
cd evaldeck
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

evaldeck validate examples/cases.jsonl --replay examples/baseline.jsonl
evaldeck run examples/cases.jsonl --replay examples/baseline.jsonl \
  --out reports/baseline --label "Synthetic baseline"

evaldeck run examples/cases.jsonl --replay examples/candidate.jsonl \
  --baseline reports/baseline/report.json \
  --out reports/candidate --label "Synthetic candidate"
```

The baseline passes **5/5** cases. The candidate deliberately fails **2/5** and exits **3**: it routes a billing ticket to the wrong category and returns an amount as text. Open `reports/candidate/report.html` in your browser to inspect both failures. The candidate fixtures are reordered to demonstrate ID-based comparison.

All example prompts and outputs are hand-authored, synthetic fixtures—not results from a live model and not a model-quality benchmark. The literal-markup case demonstrates that a report displays `<script>` text safely. Replay timings measure local fixture lookup, not inference. No token counts are fabricated when a fixture does not supply them.

A generated example is checked in as [HTML](examples/sample-report/report.html) and [JSON](examples/sample-report/report.json). Download the HTML or open it locally; GitHub displays its source.

On Windows, activate with `.venv\Scripts\Activate.ps1`. To run directly from the source tree without installing the package, use `PYTHONPATH=src python -m evaldeck …` on a POSIX shell.

## Write a dataset

One JSON object per line; IDs must be unique. Blank lines are ignored. Unknown fields, duplicate JSON keys, invalid pointers, non-finite numbers, unpaired Unicode surrogates, nesting beyond 128 levels, and empty check lists are rejected before a provider is used.

```json
{"id":"invoice","prompt":"Extract the amount and currency from: USD 19.95. Return JSON.","checks":[{"type":"json"},{"type":"required_keys","keys":["amount","currency"]},{"type":"equals","path":"/currency","value":"USD"},{"type":"number_range","path":"/amount","min":19.95,"max":19.95}]}
```

| Check | Required fields | Behavior |
| --- | --- | --- |
| `json` | `type` | Strict JSON; Markdown fences are not stripped. |
| `required_keys` | `keys` | Requires a JSON object containing every key. Extra keys are allowed. Optional `path` selects a nested object. |
| `equals` | `value` | Exact text by default. With `path`, compares a JSON value; booleans are distinct from numbers. |
| `contains` | non-empty string `value` | Case-sensitive substring in text, or in a string selected by `path`. |
| `number_range` | `path`, `min` and/or `max` | Inclusive range; strings and booleans do not count as numbers. |

An empty `path` selects the parsed JSON root. `/items/0/name` selects an array item. Use `~1` for `/` and `~0` for `~` inside a key. Missing values and explicit `null` are different. Equality does not trim whitespace or coerce strings; JSON numbers `1` and `1.0` compare equal. Numeric arithmetic follows Python's JSON integer / floating-point behavior, not decimal accounting semantics.

Replay fixtures also use JSONL:

```json
{"id":"invoice","output":"{\"amount\":19.95,\"currency\":\"USD\"}"}
```

Fixture IDs must match the dataset exactly. Optional `usage` may contain non-negative integer `input_tokens`, `output_tokens`, and `total_tokens`; if all three are supplied, the total must match. These values are labeled as fixture data, not measured usage.

## Compare and gate a change

```sh
evaldeck compare reports/baseline/report.json reports/candidate/report.json
```

| Exit | Meaning |
| --- | --- |
| `0` | Every current case passed; no baseline regression. |
| `1` | At least one current case failed or had a provider error. |
| `2` | Invalid input, incompatible baseline, configuration, or file error. |
| `3` | A formerly passing case now fails/errors, or a baseline case was removed. |

When comparing, regression status takes precedence over ordinary failures. Added cases are listed and still count toward current failures. Removing any baseline case is a regression so a deleted test cannot quietly turn the gate green. Comparison is by ID, not line order. Each case stores a SHA-256 fingerprint of its prompt and checks: changed expectations are deliberately incomparable, even when the ID is unchanged. Review such changes and generate a fresh baseline in a separate directory.

The gate evaluates case status only; it does not treat latency or token changes as regressions. `fail → error` is still a current failure, but is not a new regression from a previously passing case.

## Optional live evaluations

Live requests require `--live` plus three explicit environment variables:

```sh
export EVALDECK_API_URL="https://api.openai.com/v1/chat/completions"
export EVALDECK_MODEL="YOUR_SUPPORTED_MODEL_ID"
# Set EVALDECK_API_KEY securely in your shell or CI secret settings.
# Do not put credentials in a dataset, source file, or command argument.

evaldeck run examples/cases.jsonl --live \
  --timeout 30 --max-tokens 512 --out reports/live
```

This sends prompts to the endpoint you configure and may incur provider costs. There is no default model and no hidden API call in replay, validate, compare, or tests. The adapter sends one user message and `max_completion_tokens`; it does not set a temperature or request JSON mode. Provider/model support for these fields varies. OpenAI recommends Responses for new OpenAI-specific integrations; EvalDeck deliberately uses a small Chat Completions adapter for compatible endpoints and does not claim support for every provider or newer platform feature.

The adapter requires HTTPS, refuses redirects, caps each response at 2 MiB, and treats non-`stop` completion reasons as provider errors so truncated output cannot pass accidentally. HTTP errors include the status but omit response bodies and URLs. It uses the system's normal TLS trust and proxy environment. Each request has a socket timeout, not a strict whole-run deadline; there are no retries, concurrent requests, rate-limit scheduling, streaming, tool calls, or resumable runs.

**Privacy:** Reports intentionally contain the full prompt and output. Review them before sharing; do not run sensitive examples in public CI. The API key is not recorded. A provider could echo any text back, so output is not automatically redacted. `reports/`, `.env`, and virtual environments are ignored by Git.

## Architecture and tradeoffs

```text
JSONL dataset ── strict schema ── Case + fingerprint
                                      │
                               replay / HTTPS provider
                                      │
                            deterministic expectation checks
                                      │
                             result + status + observed timing
                                      │
                      baseline comparison ── JSON + escaped HTML
```

`schema.py` owns input validation, `providers.py` owns I/O, `checks.py` stays deterministic, `runner.py` owns case isolation and comparison, and `report.py` renders results. Provider failures are recorded per case and do not prevent later cases from running. Programming errors are not silently converted into model failures. The CLI validates datasets, fixtures, and baseline compatibility before issuing requests.

There is no database, model judge, framework dependency, or plugin loader. That keeps a small contract suite easy to review and run in CI. It also limits what the result means: passing a handful of deterministic checks cannot establish semantic correctness, safety, fairness, or production reliability. Live outputs may vary even when prompts do not. Larger suites should add representative datasets, repeated trials, statistical analysis, and human review.

Reports are versioned with `schema_version: 1`. Input files are not overwritten. Re-running an output directory replaces its two report files; each file is written atomically, but the pair is not a transaction. Keep baseline and candidate outputs in separate directories. Files are loaded into memory; this is intended for small evaluation suites, not untrusted multi-gigabyte datasets.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel . --no-deps --wheel-dir dist
evaldeck --help
```

The tests cover input errors, numeric edge cases, JSON Pointer behavior, fixture mismatches, baseline regressions, removed/changed cases, CLI exit codes, HTML escaping, bounded HTTP responses, timeouts, redirection policy, malformed responses, and secret-safe provider errors. HTTP behavior is tested with mocks; no paid requests or model downloads are part of the suite.

The runtime and test suite use only the Python standard library. The sole build dependency is pinned in `pyproject.toml`; there is no runtime dependency graph requiring a lockfile. CI tests Python 3.11–3.13 and runs the offline regression demo with read-only repository permission.

## Reference decisions

- [OpenAI Chat Completions request contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): checked for request fields and completion reasons.
- [Python urllib.request](https://docs.python.org/3/library/urllib.request.html): HTTP transport, socket timeout, and redirect handler behavior.
- [JSON Pointer, RFC 6901](https://www.rfc-editor.org/rfc/rfc6901): nested selection and escaping rules.

Built by [Elliott Barnes](https://github.com/elliottbarnes). MIT licensed. This is a portfolio engineering project with a reproducible local demo, not a hosted service or a claim of production adoption.
