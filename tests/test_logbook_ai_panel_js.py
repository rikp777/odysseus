import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node_eval(source: str):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_logbook_ai_panel_rendering_keeps_usage_preview_and_actions():
    values = _node_eval(
        """
        import { aiModeMeta, renderAIPanelHtml } from './static/js/logbook/ai-panel.js';

        const escapeHtml = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
        const html = renderAIPanelHtml({
          aiStatus: { available: true, model: 'utility-model' },
          selectedMode: 'extract_facts',
          entryContent: 'entry body',
          estimate: { input_tokens: 11, max_output_tokens: 40, total_tokens: 51, cost: { display: '$0.01', known: true } },
          actual: { total_tokens: 33, cost: { display: '$0.02', known: true } },
          usage: {
            billing: { enabled: true },
            day: { total_tokens: 77, display: '$0.07' },
            month: { total_tokens: 900, display: '$0.90' }
          },
          preview: {
            preview_content: 'Draft <one>',
            questions: ['What next?'],
            people_suggestions: [{ display_name: 'Alex', reason: 'known person' }],
            location_suggestions: [{ display_name: 'Office', reason: 'visited' }],
            usage: {
              mode: 'extract_facts',
              actual: { total_tokens: 12, cost: { display: '$0.03', known: true }, usage_source: 'provider' },
              billing: { enabled: true }
            }
          },
          escapeHtml,
          icon: (kind, size) => `<i data-kind="${kind}" data-size="${size}"></i>`,
          renderLogbookText: value => `<rendered>${escapeHtml(value)}</rendered>`,
          formatCompactTokens: value => `${value}t`,
          formatMoneyDisplay: (display, fallback) => display || fallback,
          estimateEntryTokens: () => 99,
          personSuggestionMeta: person => person.reason,
          personSuggestionActionLabel: () => 'Review'
        });

        console.log(JSON.stringify({
          fallbackMode: aiModeMeta('new_mode').label,
          hasModel: html.includes('utility-model'),
          hasFactsRun: html.includes('Run fact extraction'),
          hasLedger: html.includes('<strong>Today</strong>77t tokens | $0.07') && html.includes('<strong>Month</strong>900t tokens | $0.90'),
          hasRenderedPreview: html.includes('<rendered>Draft &lt;one&gt;</rendered>'),
          hasPersonAction: html.includes('data-add-ai-person="0">Review</button>'),
          hasLocationAction: html.includes('data-add-ai-location="0">Add</button>'),
          hasReceipt: html.includes('12t') && html.includes('$0.03')
        }));
        """
    )

    assert values == {
        "fallbackMode": "new mode",
        "hasModel": True,
        "hasFactsRun": True,
        "hasLedger": True,
        "hasRenderedPreview": True,
        "hasPersonAction": True,
        "hasLocationAction": True,
        "hasReceipt": True,
    }


def test_logbook_ai_panel_event_binding_delegates_to_app_callbacks():
    values = _node_eval(
        """
        import { bindAIPanelEvents } from './static/js/logbook/ai-panel.js';

        function element(dataset = {}) {
          return {
            dataset,
            listeners: {},
            addEventListener(type, fn) { this.listeners[type] = fn; }
          };
        }

        const mode = element({ aiMode: 'summarize' });
        const run = element();
        const clear = element();
        const apply = element();
        const copy = element();
        const mood = element();
        const data = element();
        const calls = [];
        let selected = 'structure_day';
        const root = {
          querySelectorAll(selector) {
            return selector === '[data-ai-mode]' ? [mode] : [];
          },
          querySelector(selector) {
            return ({
              '#logbook-run-ai': run,
              '#logbook-clear-ai': clear,
              '#logbook-apply-ai': apply,
              '#logbook-copy-ai': copy,
              '#logbook-apply-ai-mood': mood,
              '#logbook-add-ai-data': data
            })[selector] || null;
          }
        };

        bindAIPanelEvents(root, {
          addData: () => calls.push(['data']),
          applyContent: () => calls.push(['apply']),
          applyMood: () => calls.push(['mood']),
          bindEntityLinks: target => calls.push(['links', target === root]),
          bindSuggestions: target => calls.push(['suggestions', target === root]),
          clearAI: () => calls.push(['clear']),
          copyAI: () => calls.push(['copy']),
          extractFacts: () => { calls.push(['facts']); return Promise.resolve(); },
          runAI: value => { calls.push(['run', value]); return Promise.resolve(); },
          selectedMode: () => selected,
          selectMode: value => { selected = value; calls.push(['select', value]); }
        });

        mode.listeners.click();
        run.listeners.click();
        selected = 'extract_facts';
        run.listeners.click();
        apply.listeners.click();
        copy.listeners.click();
        clear.listeners.click();
        mood.listeners.click();
        data.listeners.click();

        console.log(JSON.stringify({ calls }));
        """
    )

    assert values == {
        "calls": [
            ["suggestions", True],
            ["links", True],
            ["select", "summarize"],
            ["run", "summarize"],
            ["facts"],
            ["apply"],
            ["copy"],
            ["clear"],
            ["mood"],
            ["data"],
        ]
    }
