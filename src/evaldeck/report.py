"""Portable reports. All variable content is escaped; no scripts or remote assets."""

from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
import tempfile


def _text(value) -> str:
    return escape(str(value), quote=True)


def render_html(report: dict) -> str:
    summary = report["summary"]
    comparison = report.get("comparison")
    comparison_html = ""
    if comparison:
        items = "".join(f"<li><strong>{_text(key.title())}</strong>: {_text(', '.join(comparison[key]) or 'none')}</li>" for key in ("regressions", "improvements", "added", "removed"))
        comparison_html = f'<section class="comparison"><h2>Baseline comparison</h2><ul>{items}</ul><p>Removed cases count as regressions. Changed prompts or checks require a reviewed new baseline.</p></section>'
    cards = []
    for case in report["cases"]:
        rows = "".join(
            f'<tr><td>{_text(check["check"]["type"])}</td><td>{"PASS" if check["passed"] else "FAIL"}</td><td>{_text(check["detail"])}</td></tr>'
            for check in case["checks"]
        )
        checks_html = f'<div class="table-scroll"><table><caption>Expectation checks</caption><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else ""
        error = f'<p class="error">{_text(case["error"])}</p>' if case["error"] else ""
        usage = json.dumps(case["usage"], sort_keys=True) if case["usage"] is not None else "not supplied"
        status = case["status"] if case["status"] in ("pass", "fail", "error") else "error"
        cards.append(f'''<article class="case {status}">
<header><h2>{_text(case["id"])}</h2><span class="badge">{_text(status.upper())}</span></header>
<p class="metadata">{_text(case["latency_ms"])} ms · token usage: {_text(usage)}</p>
<details><summary>Prompt</summary><pre>{_text(case["prompt"])}</pre></details>
<h3>Output</h3><pre>{_text(case["output"] if case["output"] is not None else 'No output')}</pre>
{error}{checks_html}</article>''')
    metrics = "".join(f'<div><strong>{summary[key]}</strong><span>{key.title()}</span></div>' for key in ("total", "pass", "fail", "error"))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="color-scheme" content="dark light"><title>EvalDeck · {_text(report.get("label") or 'Evaluation report')}</title>
<style>
:root {{ color-scheme: dark; font: 16px/1.65 ui-sans-serif, system-ui, sans-serif; background: #0c1322; color: #e8eef8; }}
* {{ box-sizing: border-box; }} body {{ max-width: 1060px; margin: auto; padding: 48px 24px 72px; }}
.eyebrow {{ color: #79e5cd; font: 700 13px ui-monospace, monospace; letter-spacing: .13em; text-transform: uppercase; }}
h1 {{ margin: 16px 0 8px; font-size: clamp(32px,5vw,54px); letter-spacing: -.04em; line-height: 1.1; }}
h2 {{ font-size: 20px; margin: 0; overflow-wrap: anywhere; }} h3 {{ font-size: 14px; color: #b7c8de; }}
p {{ margin: 10px 0; }} .metadata, .intro, footer {{ color: #b7c8de; font-size: 14px; overflow-wrap: anywhere; }}
.metrics {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 16px; margin: 32px 0; }}
.metrics div {{ padding: 18px; background: #162137; border: 1px solid #2a3b54; border-radius: 14px; }}
.metrics strong {{ display: block; font-size: 34px; }} .metrics span {{ color: #b7c8de; }}
.case, .comparison {{ border: 1px solid #2a3b54; background: #111c2e; border-radius: 16px; margin: 20px 0; padding: 24px; }}
.case header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }}
.badge {{ color: #79e5cd; background: #123e38; border-radius: 6px; padding: 3px 10px; font: 700 12px/1.6 ui-monospace, monospace; }}
.fail .badge {{ color: #ffd092; background: #4b3220; }} .error .badge {{ color: #ffbac5; background: #502835; }}
pre {{ background: #0b1423; border: 1px solid #263650; padding: 16px; border-radius: 9px; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.6 ui-monospace, monospace; }}
summary {{ cursor: pointer; color: #9acaff; }} summary:focus-visible {{ outline: 2px solid #9acaff; outline-offset: 5px; }}
.table-scroll {{ overflow-x: auto; }} table {{ width: 100%; text-align: left; border-collapse: collapse; font-size: 13px; }}
caption {{ text-align: left; color: #b7c8de; padding: 12px 0; }} th, td {{ border-top: 1px solid #2a3b54; padding: 10px 12px 10px 0; vertical-align: top; overflow-wrap: anywhere; }}
th {{ color: #b7c8de; }} .error {{ color: #ffbac5; }} footer {{ margin-top: 30px; }}
@media(max-width:600px) {{ body {{ padding: 28px 16px; }} .case,.comparison {{ padding: 18px; }} .metrics {{ gap: 8px; }} .metrics div {{ padding: 12px; }} .metrics strong {{ font-size: 26px; }} .metrics span {{ font-size: 12px; }} }}
</style></head><body>
<div class="eyebrow">EvalDeck / evaluation report</div><h1>{_text(report.get("label") or 'Inspect the output.')}</h1>
<p class="intro">Provider: {_text(report["provider"])} · Model: {_text(report["model"] or 'offline fixtures')} · {_text(report["created_at"])}</p>
<p class="intro">{_text(report["latency_note"])}. Token usage source: {_text(report["usage_source"])}.</p>
<section class="metrics" aria-label="Run summary">{metrics}</section>{comparison_html}{''.join(cards)}
<footer>EvalDeck {_text(report['evaldeck_version'])} · Deterministic contract checks, not a measure of overall model quality. This report contains prompts and outputs; review before sharing.</footer>
</body></html>'''


def _atomic_write(path: Path, content: str) -> None:
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            name = handle.name
            handle.write(content)
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


def write_report(report: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path, html_path = directory / "report.json", directory / "report.html"
    # Render both before touching outputs. Each replacement is atomic, not the pair.
    payload = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    html = render_html(report)
    _atomic_write(json_path, payload)
    _atomic_write(html_path, html)
    return json_path, html_path
