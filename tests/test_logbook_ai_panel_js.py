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
            mood_suggestion: { label: 'steady', score: 4 },
            questions: ['What next?'],
            datapoint_suggestions: [{ key: 'sleep', label: 'Sleep', value_text: '7h' }],
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
          hasEnhanceHeader: html.includes('<h5>Enhance</h5>'),
          hasBackButton: html.includes('id="logbook-back-to-write"'),
          hasModel: html.includes('utility-model'),
          hasFactsRun: html.includes('Extract saved facts'),
          hasLedger: html.includes('<strong>Today</strong>77t tokens | $0.07') && html.includes('<strong>Month</strong>900t tokens | $0.90'),
          hasRenderedPreview: html.includes('<rendered>Draft &lt;one&gt;</rendered>'),
          hasMoodAction: html.includes('id="logbook-apply-ai-mood"'),
          hasDataAction: html.includes('data-add-ai-data-index="0"'),
          hasDismissAction: html.includes('data-dismiss-ai-suggestion="data:0"'),
          hasPersonAction: html.includes('data-add-ai-person="0">Review</button>'),
          hasLocationAction: html.includes('data-add-ai-location="0">Add</button>'),
          hasReceipt: html.includes('12t') && html.includes('$0.03')
        }));
        """
    )

    assert values == {
        "fallbackMode": "new mode",
        "hasEnhanceHeader": True,
        "hasBackButton": True,
        "hasModel": True,
        "hasFactsRun": True,
        "hasLedger": True,
        "hasRenderedPreview": True,
        "hasMoodAction": True,
        "hasDataAction": True,
        "hasDismissAction": True,
        "hasPersonAction": True,
        "hasLocationAction": True,
        "hasReceipt": True,
    }


def test_logbook_ai_panel_defaults_to_detect_entry_structure():
    values = _node_eval(
        """
        import { aiModeMeta, renderAIPanelHtml } from './static/js/logbook/ai-panel.js';

        const html = renderAIPanelHtml({
          aiStatus: { available: true, model: 'utility-model' },
          entryContent: 'Breakfast with Jan at the gym',
        });
        const detect = aiModeMeta('extract_all');
        const rewrite = aiModeMeta('structure_day');

        console.log(JSON.stringify({
          detectLabel: detect.label,
          detectDetail: detect.detail,
          rewriteLabel: rewrite.label,
          hasDetectActive: html.includes('data-ai-mode="extract_all"') && html.includes('logbook-ai-command primary active'),
          hasHelpfulEmptyState: html.includes('people, places, meals, mood, and data suggestions'),
          hasNoOldEmptyState: !html.includes('Enhancement previews appear here')
        }));
        """
    )

    assert values == {
        "detectLabel": "Detect",
        "detectDetail": "People, places, meals",
        "rewriteLabel": "Rewrite",
        "hasDetectActive": True,
        "hasHelpfulEmptyState": True,
        "hasNoOldEmptyState": True,
    }


def test_logbook_ai_panel_hides_dismissed_queue_items_and_can_restore_them():
    values = _node_eval(
        """
        import { renderAIPanelHtml } from './static/js/logbook/ai-panel.js';

        const html = renderAIPanelHtml({
          aiStatus: { available: true, model: 'utility-model' },
          dismissedSuggestions: ['content', 'data:0', 'person:0'],
          preview: {
            preview_content: 'Hidden rewrite',
            datapoint_suggestions: [{ key: 'sleep', label: 'Sleep', value_text: '7h' }],
            people_suggestions: [{ display_name: 'Alex', reason: 'known person' }],
            location_suggestions: [{ display_name: 'Office', reason: 'visited' }]
          }
        });

        console.log(JSON.stringify({
          hidesContent: !html.includes('Hidden rewrite'),
          hidesData: !html.includes('data-add-ai-data-index="0"'),
          hidesPerson: !html.includes('data-add-ai-person="0"'),
          keepsLocation: html.includes('data-add-ai-location="0"'),
          hasRestore: html.includes('id="logbook-restore-ai-suggestions"')
        }));
        """
    )

    assert values == {
        "hidesContent": True,
        "hidesData": True,
        "hidesPerson": True,
        "keepsLocation": True,
        "hasRestore": True,
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
        const back = element();
        const copy = element();
        const mood = element();
        const data = element();
        const dataOne = element({ addAiDataIndex: '2' });
        const dismiss = element({ dismissAiSuggestion: 'data:2' });
        const restore = element();
        const calls = [];
        let selected = 'structure_day';
        const root = {
          querySelectorAll(selector) {
            if (selector === '[data-ai-mode]') return [mode];
            if (selector === '[data-add-ai-data-index]') return [dataOne];
            if (selector === '[data-dismiss-ai-suggestion]') return [dismiss];
            return [];
          },
          querySelector(selector) {
            return ({
              '#logbook-run-ai': run,
              '#logbook-back-to-write': back,
              '#logbook-clear-ai': clear,
              '#logbook-apply-ai': apply,
              '#logbook-copy-ai': copy,
              '#logbook-apply-ai-mood': mood,
              '#logbook-add-ai-data': data,
              '#logbook-restore-ai-suggestions': restore
            })[selector] || null;
          }
        };

        bindAIPanelEvents(root, {
          addData: value => calls.push(['data', value ?? null]),
          applyContent: () => calls.push(['apply']),
          applyMood: () => calls.push(['mood']),
          backToWrite: () => calls.push(['back']),
          bindEntityLinks: target => calls.push(['links', target === root]),
          bindSuggestions: target => calls.push(['suggestions', target === root]),
          clearAI: () => calls.push(['clear']),
          copyAI: () => calls.push(['copy']),
          dismissAISuggestion: key => calls.push(['dismiss', key]),
          extractFacts: () => { calls.push(['facts']); return Promise.resolve(); },
          restoreAISuggestions: () => calls.push(['restore']),
          runAI: value => { calls.push(['run', value]); return Promise.resolve(); },
          selectedMode: () => selected,
          selectMode: value => { selected = value; calls.push(['select', value]); }
        });

        mode.listeners.click();
        run.listeners.click();
        selected = 'extract_facts';
        run.listeners.click();
        back.listeners.click();
        apply.listeners.click();
        copy.listeners.click();
        clear.listeners.click();
        mood.listeners.click();
        data.listeners.click();
        dataOne.listeners.click();
        dismiss.listeners.click();
        restore.listeners.click();

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
            ["back"],
            ["apply"],
            ["copy"],
            ["clear"],
            ["mood"],
            ["data", None],
            ["data", 2],
            ["dismiss", "data:2"],
            ["restore"],
        ]
    }
