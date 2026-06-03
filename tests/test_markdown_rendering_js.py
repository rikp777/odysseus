"""Regression coverage for the browser markdown renderer."""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _run_markdown_case(markdown: str) -> str:
    script = textwrap.dedent(
        r"""
        import fs from 'node:fs';

        globalThis.window = { location: { origin: 'http://localhost' }, katex: null };
        globalThis.document = {
          readyState: 'loading',
          addEventListener() {},
        };
        globalThis.MutationObserver = class { observe() {} };

        let source = fs.readFileSync('./static/js/markdown.js', 'utf8');
        source = source.replace(
          /import uiModule from ['"]\.\/ui\.js['"];/,
          ''
        );
        source = source.replace(
          /import \{ splitTableRow \} from ['"]\.\/markdown\/tableRow\.js['"];/,
          `function splitTableRow(row) {
            return (row || '').replace(/^\\s*\\|/, '').replace(/\\|\\s*$/, '').split('|').map(c => c.trim());
          }`
        );
        source = source.replace(
          /var escapeHtml = uiModule\.esc;/,
          `var escapeHtml = (value) => String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');`
        );

        const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
        const mod = await import(moduleUrl);
        const input = JSON.parse(process.argv[1]);
        console.log(JSON.stringify({ html: mod.mdToHtml(input) }));
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(markdown)],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"node failed:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}")
    return json.loads(result.stdout.splitlines()[-1])["html"]


def test_ordered_lists_render_as_one_unwrapped_ol(node_available):
    html = _run_markdown_case(
        "Before\n\n"
        "1. **Check against the home page** — that's the visual reference for how things should feel.\n"
        "2. **Open DevTools** and inspect the element — check fonts, colors, and spacing against this guide.\n"
        "3. **Flag it** — note the page, the section, what's wrong, and what CSS rule you suspect.\n"
        "4. **Small fixes** — if you know the fix (e.g. wrong CSS variable, wrong font), go ahead and change it in the CSS Module file.\n"
        "5. **Big changes** — Talk it through before making wide changes across many pages.\n\n"
        "After"
    )

    assert html.count("<ol>") == 1
    assert html.count("</ol>") == 1
    assert html.count("<li>") == 5
    assert "<ul>" not in html
    assert "<oli>" not in html
    assert "<uli>" not in html
    assert "<p><ol>" not in html
    assert "<p><li>" not in html
    assert "<p>Before</p>" in html
    assert "<p>After</p>" in html


def test_billing_chart_renders_usage_breakdown(node_available):
    chart = {
        "version": 1,
        "kind": "billing-spend",
        "title": "Model Spend by Model",
        "subtitle": "Today",
        "enabled": True,
        "configured": True,
        "total": 0.65,
        "total_display": "$0.65",
        "projected": 0.65,
        "projected_display": "$0.65",
        "source_note": "Model spend from usage ledger estimates",
        "usage": {
            "events": 2,
            "input_tokens": 30,
            "output_tokens": 12,
            "total_tokens": 42,
            "known_cost_events": 1,
            "unknown_cost_events": 1,
            "source_label": "Usage ledger",
        },
        "accounts": [
            {
                "label": "gpt-4o",
                "provider_label": "Local usage",
                "amount": 0.65,
                "display": "$0.65",
                "ok": True,
                "source_label": "Usage estimate",
                "usage": {
                    "events": 2,
                    "input_tokens": 30,
                    "output_tokens": 12,
                    "total_tokens": 42,
                    "known_cost_events": 1,
                    "unknown_cost_events": 1,
                },
            }
        ],
        "history": [],
    }

    html = _run_markdown_case("```billing-chart\n" + json.dumps(chart) + "\n```")

    assert "Model Spend by Model" in html
    assert "Model spend from usage ledger estimates" in html
    assert "Usage estimate" in html
    assert "Tokens" in html
    assert "Calls" in html
    assert "gpt-4o" in html
    assert "42 tokens" in html
    assert "2 calls" in html
    assert "1 unpriced" in html


def test_billing_chart_hides_provider_account_total_for_model_spend(node_available):
    chart = {
        "version": 1,
        "kind": "billing-spend",
        "title": "Model Spend",
        "subtitle": "June 2026 month-to-date",
        "enabled": True,
        "configured": True,
        "total": 0.68,
        "total_display": "$0.68",
        "projected": 6.8,
        "projected_display": "$6.80",
        "period": "month",
        "spend_source": "provider_model_billing",
        "spend_scope": "model_usage",
        "provider_total": 6.44,
        "provider_total_display": "$6.44",
        "source_note": "Model spend from provider billing insights; provider billing is account-level and can include non-model services",
        "notice": "Provider account billing reports $6.44 across all services; it is not used for the model spend total.",
        "accounts": [],
        "history": [],
    }

    html = _run_markdown_case("```billing-chart\n" + json.dumps(chart) + "\n```")

    assert "Model spend from provider billing insights" in html
    assert "provider billing is account-level" not in html
    assert "Provider account billing reports" not in html
    assert "Account</span><strong>$6.44" not in html


def test_billing_chart_history_points_are_hoverable(node_available):
    chart = {
        "version": 1,
        "kind": "billing-spend",
        "title": "Model Spend",
        "subtitle": "June 2026 month-to-date",
        "enabled": True,
        "configured": True,
        "total": 0.68,
        "total_display": "$0.68",
        "projected": 6.8,
        "projected_display": "$6.80",
        "period": "month",
        "days_elapsed": 3,
        "days_in_month": 30,
        "warning": 1.0,
        "warning_display": "$1.00",
        "limit": 5.0,
        "limit_display": "$5.00",
        "monthly_warning": 1.0,
        "monthly_warning_display": "$1.00",
        "monthly_limit": 5.0,
        "monthly_limit_display": "$5.00",
        "accounts": [],
        "history": [
            {"timestamp": "2026-06-01T08:00:00Z", "amount": 0.12, "display": "$0.12", "synthetic": True},
            {"timestamp": "2026-06-03T08:00:00Z", "amount": 0.68, "display": "$0.68"},
        ],
    }

    html = _run_markdown_case("```billing-chart\n" + json.dumps(chart) + "\n```")

    assert html.count("billing-chart-actual-point") == 2
    assert html.count("billing-chart-projection-mode-point") == 2
    assert html.count("billing-chart-projected-point") == 1
    assert "billing-chart-threshold-toggle" in html
    assert "billing-chart-threshold-layer" in html
    assert "billing-chart-threshold-warning" in html
    assert "billing-chart-threshold-limit" in html
    assert "billing-chart-projection-toggle" in html
    assert "billing-chart-projection-line" in html
    assert "billing-chart-axis-labels-projected" in html
    assert "data-chart-x=" in html
    assert "data-chart-y=" in html
    assert 'aria-label="Jun 1: $0.12"' in html
    assert 'title="Jun 3: $0.68"' in html
    assert 'aria-label="Show monthly warning and max usage lines"' in html
    assert 'aria-label="Show projected spend line"' in html
    assert "Month warn: $1.00" in html
    assert "Month max: $5.00" in html
    assert 'aria-label="Projected month-end: $6.80"' in html
    assert "billing-chart-data-points" in html
    assert "2 points + projection" in html
    assert "Baseline" in html
    assert "Actual" in html
    assert "Projected" in html
    assert "Jun 30" in html


def test_billing_chart_threshold_lines_use_period_specific_fields_only(node_available):
    chart = {
        "version": 1,
        "kind": "billing-spend",
        "title": "Model Spend",
        "subtitle": "Today",
        "enabled": True,
        "configured": True,
        "total": 0.68,
        "total_display": "$0.68",
        "projected": 0.68,
        "projected_display": "$0.68",
        "period": "day",
        "warning": 1.0,
        "warning_display": "$1.00",
        "limit": 2.0,
        "limit_display": "$2.00",
        "accounts": [],
        "history": [
            {"timestamp": "2026-06-03T08:00:00Z", "amount": 0.12, "display": "$0.12"},
            {"timestamp": "2026-06-03T09:00:00Z", "amount": 0.68, "display": "$0.68"},
        ],
    }

    html = _run_markdown_case("```billing-chart\n" + json.dumps(chart) + "\n```")

    assert "billing-chart-threshold-toggle" not in html
    assert "billing-chart-threshold-layer" not in html
    assert "Month max: $2.00" not in html


def test_billing_chart_daily_threshold_lines_use_daily_fields(node_available):
    chart = {
        "version": 1,
        "kind": "billing-spend",
        "title": "Model Spend",
        "subtitle": "Today",
        "enabled": True,
        "configured": True,
        "total": 0.68,
        "total_display": "$0.68",
        "projected": 0.68,
        "projected_display": "$0.68",
        "period": "day",
        "warning": 0.5,
        "warning_display": "$0.50",
        "limit": 1.0,
        "limit_display": "$1.00",
        "daily_warning": 0.5,
        "daily_warning_display": "$0.50",
        "daily_limit": 1.0,
        "daily_limit_display": "$1.00",
        "accounts": [],
        "history": [
            {"timestamp": "2026-06-03T08:00:00Z", "amount": 0.12, "display": "$0.12"},
            {"timestamp": "2026-06-03T09:00:00Z", "amount": 0.68, "display": "$0.68"},
        ],
    }

    html = _run_markdown_case("```billing-chart\n" + json.dumps(chart) + "\n```")

    assert "billing-chart-threshold-toggle" in html
    assert 'aria-label="Show daily warning and max usage lines"' in html
    assert "Day warn: $0.50" in html
    assert "Day max: $1.00" in html
    assert "Month warn" not in html


def test_billing_chart_renders_month_navigation(node_available):
    chart = {
        "version": 1,
        "kind": "billing-spend",
        "title": "Model Spend",
        "subtitle": "May 2026",
        "enabled": True,
        "configured": True,
        "total": 0.4,
        "total_display": "$0.40",
        "projected": 0.4,
        "projected_display": "$0.40",
        "period": "month",
        "month": "2026-05",
        "month_label": "May 2026",
        "previous_month": "2026-04",
        "next_month": "2026-06",
        "group_by": "model",
        "spend_source": "provider_model_billing",
        "spend_scope": "model_usage",
        "history": [
            {"timestamp": "2026-05-01T00:00:00Z", "amount": 0.0, "display": "$0.00"},
            {"timestamp": "2026-05-10T08:00:00Z", "amount": 0.4, "display": "$0.40"},
        ],
        "accounts": [],
    }

    html = _run_markdown_case("```billing-chart\n" + json.dumps(chart) + "\n```")

    assert "billing-chart-month-nav" in html
    assert "May 2026" in html
    assert 'data-billing-chart-month="2026-04"' in html
    assert 'data-billing-chart-month="2026-06"' in html
    assert 'data-billing-group-by="model"' in html
    assert 'data-billing-spend-source="provider_model_billing"' in html
    assert 'data-billing-spend-scope="model_usage"' in html
    assert "edge-start" in html
    assert "edge-end" in html


def test_table_separator_row_not_rendered_as_data(node_available):
    html = _run_markdown_case("| A | B |\n|---|---|\n| 1 | 2 |")

    assert html.count("<tr>") == 2
    assert "<th" in html
    assert "<td" in html
    assert "---" not in html
