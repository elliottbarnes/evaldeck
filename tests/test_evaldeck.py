from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from http.client import IncompleteRead
from io import BytesIO, StringIO
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from evaldeck.checks import evaluate
from evaldeck.cli import main
from evaldeck.providers import ChatHTTPProvider, Completion, MAX_RESPONSE_BYTES, ProviderError, ReplayProvider, _NoRedirect
from evaldeck.report import render_html, write_report
from evaldeck.runner import compare, exit_code, load_report, run
from evaldeck.schema import Case, InputError, load_cases, loads, number


class TemporaryFiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def jsonl(self, name, records):
        path = self.root / name
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return path

    def cases(self):
        return [Case("a", "Say hello", [{"type": "equals", "value": "hello"}]), Case("b", "Say yes", [{"type": "contains", "value": "yes"}])]

    def report(self, outputs=None):
        outputs = outputs or {"a": "hello", "b": "yes"}
        fixture = self.jsonl("fixtures.jsonl", [{"id": key, "output": output} for key, output in outputs.items()])
        cases = self.cases()
        return run(cases, ReplayProvider(fixture, cases), label="Synthetic test")


class SchemaTests(TemporaryFiles):
    def test_valid_dataset_and_blank_lines(self):
        path = self.jsonl("cases.jsonl", [{"id": "a", "prompt": "P", "checks": [{"type": "json"}]}])
        with path.open("a") as output:
            output.write("\n")
        self.assertEqual(load_cases(path)[0].id, "a")

    def test_bad_json_has_line_number(self):
        path = self.root / "cases.jsonl"
        path.write_text('\n{"id":', encoding="utf-8")
        with self.assertRaisesRegex(InputError, r"cases.jsonl:2:"):
            load_cases(path)

    def test_strict_json_rejects_duplicate_and_nonfinite_numbers(self):
        for payload in ('{"a":1,"a":2}', '{"x":NaN}', '[Infinity]', '{"x":1e999}'):
            with self.subTest(payload=payload), self.assertRaises(InputError):
                loads(payload)

    def test_large_integer_is_finite_and_bool_is_not_number(self):
        self.assertTrue(number(10 ** 400))
        self.assertFalse(number(True))
        self.assertEqual(loads(str(10 ** 400)), 10 ** 400)

    def test_reject_unpaired_surrogates_but_accept_valid_pair(self):
        for payload in ('"\\ud800"', '{"\\udfff": 1}', '{"output":"\\ud800"}'):
            with self.subTest(payload=payload), self.assertRaisesRegex(InputError, "surrogate"):
                loads(payload)
        self.assertEqual(loads('"\\ud83d\\ude80"'), "🚀")

    def test_deep_json_is_rejected_before_recursive_checks(self):
        payload = "[" * 400 + "1" + "]" * 400
        with self.assertRaisesRegex(InputError, "nesting"):
            loads(payload)
        result = evaluate(payload, [{"type": "equals", "path": "", "value": []}])[0]
        self.assertFalse(result["passed"])

    def test_missing_file_and_invalid_encoding(self):
        with self.assertRaises(InputError):
            load_cases(self.root / "missing")
        path = self.root / "bad"
        path.write_bytes(b"\xff")
        with self.assertRaises(InputError):
            load_cases(path)

    def test_empty_and_nonobject_datasets(self):
        for contents in ("\n", "[]\n", '"hello"\n'):
            path = self.root / "bad"
            path.write_text(contents)
            with self.subTest(contents=contents), self.assertRaises(InputError):
                load_cases(path)

    def test_duplicate_case_ids(self):
        record = {"id": "a", "prompt": "P", "checks": [{"type": "json"}]}
        with self.assertRaisesRegex(InputError, "duplicate case"):
            load_cases(self.jsonl("cases", [record, record]))

    def test_invalid_cases_and_checks(self):
        invalid = [
            {"id": "", "prompt": "P", "checks": [{"type": "json"}]},
            {"id": "a", "prompt": "P", "checks": []},
            {"id": "a", "prompt": "P", "checks": [{"type": "json"}], "typo": 1},
        ]
        invalid_checks = [
            {"type": "regex", "value": ".*"}, {"type": "equals"},
            {"type": "equals", "value": 1}, {"type": "contains", "value": ""},
            {"type": "json", "typo": True}, {"type": "required_keys", "keys": []},
            {"type": "required_keys", "keys": ["x", "x"]},
            {"type": "number_range", "path": "/n", "min": True},
            {"type": "number_range", "min": 1},
            {"type": "number_range", "path": "/n", "min": 2, "max": 1},
            {"type": "number_range", "path": "/n"},
            {"type": "equals", "path": "n", "value": 1},
            {"type": "equals", "path": "/~2", "value": 1},
        ]
        invalid.extend({"id": "a", "prompt": "P", "checks": [check]} for check in invalid_checks)
        for record in invalid:
            with self.subTest(record=record), self.assertRaises(InputError):
                load_cases(self.jsonl("cases", [record]))


class CheckTests(unittest.TestCase):
    def check(self, output, check):
        return evaluate(output, [check])[0]

    def test_json_validity_and_duplicate_keys(self):
        self.assertTrue(self.check('{"x":1}', {"type": "json"})["passed"])
        for text in ('```json\n{}\n```', '{"x":1,"x":2}', 'NaN'):
            self.assertFalse(self.check(text, {"type": "json"})["passed"])

    def test_contains_is_case_sensitive_and_requires_text(self):
        self.assertTrue(self.check("Hello world", {"type": "contains", "value": "world"})["passed"])
        self.assertFalse(self.check("Hello", {"type": "contains", "value": "hello"})["passed"])
        self.assertFalse(self.check('{"x":123}', {"type": "contains", "path": "/x", "value": "1"})["passed"])

    def test_json_pointer_escapes_and_arrays(self):
        output = '{"a/b":{"~key":["ok"]}}'
        self.assertTrue(self.check(output, {"type": "equals", "path": "/a~1b/~0key/0", "value": "ok"})["passed"])
        for pointer in ("/01", "/-1", "/2", "/١", "/" + "9" * 5000):
            self.assertFalse(self.check('["ok"]', {"type": "equals", "path": pointer, "value": "ok"})["passed"])

    def test_null_and_missing_are_distinct(self):
        check = {"type": "equals", "path": "/x", "value": None}
        self.assertTrue(self.check('{"x":null}', check)["passed"])
        self.assertIn("not found", self.check('{}', check)["detail"])

    def test_required_keys_nested_and_object_type(self):
        check = {"type": "required_keys", "path": "/x", "keys": ["a"]}
        self.assertTrue(self.check('{"x":{"a":null}}', check)["passed"])
        self.assertFalse(self.check('{"x":["a"]}', check)["passed"])

    def test_exact_text_has_no_implicit_normalization(self):
        self.assertFalse(self.check("yes\n", {"type": "equals", "value": "yes"})["passed"])

    def test_json_equals_distinguishes_boolean_recursively(self):
        self.assertFalse(self.check('{"x":[true]}', {"type": "equals", "path": "", "value": {"x": [1]}})["passed"])
        self.assertTrue(self.check('{"x":1.0}', {"type": "equals", "path": "/x", "value": 1})["passed"])

    def test_numeric_range_inclusive_and_no_bool_coercion(self):
        check = {"type": "number_range", "path": "", "min": 0, "max": 1}
        for value in ("0", "1", "0.5"):
            self.assertTrue(self.check(value, check)["passed"])
        for value in ("true", '"0.5"', "1.1", "null"):
            self.assertFalse(self.check(value, check)["passed"])
        self.assertTrue(self.check(str(10 ** 400), {"type": "number_range", "path": "", "min": 1})["passed"])


class ReplayTests(TemporaryFiles):
    def test_fixture_matching_is_by_id_not_order(self):
        path = self.jsonl("fixtures", [{"id": "b", "output": "yes"}, {"id": "a", "output": "hello"}])
        self.assertEqual(ReplayProvider(path, self.cases()).complete(self.cases()[0]).output, "hello")

    def test_mismatch_lists_missing_and_extra(self):
        path = self.jsonl("fixtures", [{"id": "a", "output": "hello"}, {"id": "c", "output": "yes"}])
        with self.assertRaisesRegex(InputError, "missing=\\['b'\\], extra=\\['c'\\]"):
            ReplayProvider(path, self.cases())

    def test_duplicate_fixture_and_bad_usage(self):
        for records in (
            [{"id": "a", "output": "x"}] * 2,
            [{"id": "a", "output": "x", "usage": {"total_tokens": True}}],
            [{"id": "a", "output": "x", "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 9}}],
        ):
            with self.subTest(records=records), self.assertRaises(InputError):
                ReplayProvider(self.jsonl("fixtures", records), self.cases())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"EVALDECK_API_URL": "https://provider.example/v1/chat/completions", "EVALDECK_MODEL": "test-model", "EVALDECK_API_KEY": "test-key"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.provider = ChatHTTPProvider(timeout=2.5, max_tokens=64)
        self.case = Case("a", "Return a greeting", [{"type": "contains", "value": "hi"}])

    def reply(self, payload):
        self.provider._opener = Mock()
        self.provider._opener.open.return_value = BytesIO(json.dumps(payload).encode())

    def valid_payload(self):
        return {"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}}

    def test_request_shape_and_reported_usage(self):
        self.reply(self.valid_payload())
        completion = self.provider.complete(self.case)
        request = self.provider._opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data), {"model": "test-model", "messages": [{"role": "user", "content": "Return a greeting"}], "max_completion_tokens": 64, "stream": False})
        self.assertEqual(self.provider._opener.open.call_args.kwargs, {"timeout": 2.5})
        self.assertEqual(completion.usage, {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5})

    def test_missing_usage_remains_unknown(self):
        payload = self.valid_payload()
        del payload["usage"]
        self.reply(payload)
        self.assertIsNone(self.provider.complete(self.case).usage)

    def test_provider_timeout_and_connection_errors(self):
        for error, expected in ((socket.timeout(), "timed out"), (URLError(socket.timeout()), "timed out"), (URLError("private-detail"), "connection failed")):
            self.provider._opener = Mock()
            self.provider._opener.open.side_effect = error
            with self.subTest(error=error), self.assertRaisesRegex(ProviderError, expected):
                self.provider.complete(self.case)

    def test_incomplete_http_response_is_a_provider_error(self):
        self.provider._opener = Mock()
        self.provider._opener.open.side_effect = IncompleteRead(b"private partial response")
        with self.assertRaisesRegex(ProviderError, "invalid response or connection failed") as context:
            self.provider.complete(self.case)
        self.assertNotIn("private", str(context.exception))

    def test_http_error_does_not_expose_body_url_or_key(self):
        self.provider._opener = Mock()
        self.provider._opener.open.side_effect = HTTPError("https://private-url", 429, "test-key", {}, BytesIO(b"secret prompt"))
        with self.assertRaises(ProviderError) as context:
            self.provider.complete(self.case)
        self.assertEqual(str(context.exception), "provider HTTP 429; response body omitted")

    def test_malformed_truncated_or_nontext_completions_fail(self):
        payloads = [[], {}, {"choices": [None]}, {"choices": [{"finish_reason": "length", "message": {"content": "hi"}}]}, {"choices": [{"finish_reason": "stop", "message": {"content": None}}]}]
        invalid_usage = self.valid_payload()
        invalid_usage["usage"]["total_tokens"] = "five"
        payloads.append(invalid_usage)
        for payload in payloads:
            self.reply(payload)
            with self.subTest(payload=payload), self.assertRaises(ProviderError):
                self.provider.complete(self.case)

    def test_response_size_limit_and_invalid_encoding(self):
        for data in (b"x" * (MAX_RESPONSE_BYTES + 1), b"\xff", b"{broken"):
            self.provider._opener = Mock()
            self.provider._opener.open.return_value = BytesIO(data)
            with self.subTest(size=len(data)), self.assertRaises(ProviderError):
                self.provider.complete(self.case)

    def test_credentials_and_endpoint_are_explicit(self):
        for settings in ({"EVALDECK_API_KEY": ""}, {"EVALDECK_MODEL": ""}, {"EVALDECK_API_URL": "http://provider.example"}, {"EVALDECK_API_URL": "https://name:secret@provider.example"}, {"EVALDECK_API_URL": "https://provider.example?key=secret"}, {"EVALDECK_API_URL": "https://["}, {"EVALDECK_API_URL": "https://provider.example:bad"}):
            with self.subTest(settings=settings), patch.dict("os.environ", settings), self.assertRaises(InputError):
                ChatHTTPProvider()

    def test_redirects_are_not_followed(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 307, "", {}, "https://elsewhere.example"))


class RunnerTests(TemporaryFiles):
    def test_provider_failure_does_not_stop_other_cases(self):
        provider = Mock(name="provider")
        provider.name, provider.model = "test", None
        provider.complete.side_effect = [ProviderError("timed out"), Completion("yes")]
        report = run(self.cases(), provider)
        self.assertEqual(report["summary"], {"total": 2, "pass": 1, "fail": 0, "error": 1})
        self.assertEqual(exit_code(report), 1)

    def test_reordered_reports_compare_by_id(self):
        baseline = self.report()
        current = deepcopy(baseline)
        current["cases"].reverse()
        comparison = compare(baseline, current)
        self.assertEqual(comparison["unchanged"], ["a", "b"])
        self.assertEqual(exit_code(current, comparison), 0)

    def test_regression_exit_code_and_improvement(self):
        baseline, current = self.report(), self.report({"a": "goodbye", "b": "yes"})
        comparison = compare(baseline, current)
        self.assertEqual(comparison["regressions"], ["a"])
        self.assertEqual(exit_code(current, comparison), 3)
        self.assertEqual(compare(current, baseline)["improvements"], ["a"])

    def test_removing_case_is_regression_and_additions_are_visible(self):
        baseline = self.report()
        current = deepcopy(baseline)
        current["cases"].pop()
        self.assertEqual(compare(baseline, current)["removed"], ["b"])
        self.assertTrue(compare(baseline, current)["has_regressions"])
        self.assertEqual(compare(current, baseline)["added"], ["b"])

    def test_changed_checks_are_not_comparable(self):
        baseline = self.report()
        current = deepcopy(baseline)
        current["cases"][0]["fingerprint"] = "a" * 64
        with self.assertRaisesRegex(InputError, "changed prompts/checks"):
            compare(baseline, current)

    def test_saved_report_validation(self):
        report = self.report()
        json_path, _ = write_report(report, self.root / "out")
        self.assertEqual(load_report(json_path), report)
        for mutation in ("duplicate", "summary", "status", "fingerprint"):
            bad = deepcopy(report)
            if mutation == "duplicate":
                bad["cases"].append(bad["cases"][0])
            elif mutation == "summary":
                bad["summary"]["pass"] = 99
            elif mutation == "status":
                bad["cases"][0]["checks"][0]["passed"] = False
            else:
                bad["cases"][0]["fingerprint"] = "bad"
            json_path.write_text(json.dumps(bad))
            with self.subTest(mutation=mutation), self.assertRaises(InputError):
                load_report(json_path)


class ReportTests(TemporaryFiles):
    def test_html_escapes_all_untrusted_text_and_has_no_scripts(self):
        report = self.report()
        attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        report["label"] = report["model"] = attack
        report["cases"][0].update(id=attack, prompt=attack, output=attack, error=attack)
        report["cases"][0]["checks"][0]["detail"] = attack
        report["comparison"] = {"regressions": [attack], "improvements": [], "added": [], "removed": []}
        html = render_html(report)
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertGreaterEqual(html.count("&lt;script&gt;"), 8)
        self.assertIn("Content-Security-Policy", html)

    def test_report_includes_failure_detail_and_honest_latency(self):
        html = render_html(self.report({"a": "goodbye", "b": "yes"}))
        self.assertIn("got &quot;goodbye&quot;", html)
        self.assertIn("not model inference", html)
        self.assertIn("not supplied", html)


class CLITests(TemporaryFiles):
    def setUp(self):
        super().setUp()
        self.dataset = self.jsonl("cases.jsonl", [{"id": c.id, "prompt": c.prompt, "checks": c.checks} for c in self.cases()])
        self.fixtures = self.jsonl("fixtures.jsonl", [{"id": "a", "output": "hello"}, {"id": "b", "output": "yes"}])

    def invoke(self, *args):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main([str(arg) for arg in args])
        return code, output.getvalue(), error.getvalue()

    def test_validate_and_run_offline(self):
        with patch("evaldeck.cli.ChatHTTPProvider") as live:
            code, output, _ = self.invoke("validate", self.dataset, "--replay", self.fixtures)
            self.assertEqual(code, 0)
            self.assertIn("2 cases", output)
            out = self.root / "out"
            self.assertEqual(self.invoke("run", self.dataset, "--replay", self.fixtures, "--out", out)[0], 0)
            self.assertTrue((out / "report.html").exists())
            live.assert_not_called()

    def test_comparison_cli_returns_regression_exit(self):
        baseline = self.root / "baseline"
        self.invoke("run", self.dataset, "--replay", self.fixtures, "--out", baseline)
        bad = self.jsonl("bad.jsonl", [{"id": "a", "output": "oops"}, {"id": "b", "output": "yes"}])
        current = self.root / "current"
        code, output, _ = self.invoke("run", self.dataset, "--replay", bad, "--out", current, "--baseline", baseline / "report.json")
        self.assertEqual(code, 3)
        self.assertIn("Regressions: ['a']", output)
        self.assertEqual(self.invoke("compare", baseline / "report.json", current / "report.json")[0], 3)

    def test_bad_input_errors_do_not_create_reports(self):
        out = self.root / "out"
        code, _, error = self.invoke("run", self.root / "missing", "--replay", self.fixtures, "--out", out)
        self.assertEqual(code, 2)
        self.assertIn("cannot read", error)
        self.assertFalse(out.exists())

    def test_baseline_input_cannot_be_overwritten(self):
        out = self.root / "out"
        self.invoke("run", self.dataset, "--replay", self.fixtures, "--out", out)
        before = (out / "report.json").read_bytes()
        code, _, error = self.invoke("run", self.dataset, "--replay", self.fixtures, "--out", out, "--baseline", out / "report.json")
        self.assertEqual(code, 2)
        self.assertIn("overwrite", error)
        self.assertEqual((out / "report.json").read_bytes(), before)

    def test_changed_baseline_rejected_before_live_requests(self):
        baseline = self.root / "baseline"
        self.invoke("run", self.dataset, "--replay", self.fixtures, "--out", baseline)
        changed = self.jsonl("changed.jsonl", [{"id": c.id, "prompt": "Different prompt", "checks": c.checks} for c in self.cases()])
        with patch("evaldeck.cli.ChatHTTPProvider") as live:
            code, _, error = self.invoke("run", changed, "--live", "--baseline", baseline / "report.json", "--out", self.root / "out")
            self.assertEqual(code, 2)
            self.assertIn("changed prompts", error)
            live.assert_not_called()

    def test_invalid_timeout_is_a_usage_error(self):
        for value in ("nan", "inf", "-1", "0"):
            with self.subTest(value=value), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as result:
                main(["run", str(self.dataset), "--live", "--timeout", value])
            self.assertEqual(result.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
