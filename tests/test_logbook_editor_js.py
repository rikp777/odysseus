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


def test_logbook_editor_helpers_render_and_transform_markdown_links():
    values = _node_eval(
        """
        import {
          linkedSelectionText,
          renderEditorText,
          unlinkMarkdownSelection
        } from './static/js/logbook/editor.js';

        const html = renderEditorText(
          'Saw <raw> [Jeanine](person:jeanine) at [Gym](place:gym).',
          {
            escapeHtml: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
            renderToken: (label, target) => `<token data-target="${target}">${label}</token>`
          }
        );
        const linked = linkedSelectionText('  Jeanine Peeters  ', 'person', (kind, label) => `${kind}:${label.toLowerCase().replaceAll(' ', '_')}`);
        const contained = unlinkMarkdownSelection('Saw [Jeanine](person:jeanine) today', 8, 8);
        const sample = '[Jean](person:jean) and [Gym](place:gym)';
        const selected = unlinkMarkdownSelection(sample, 0, sample.length);
        const plain = unlinkMarkdownSelection('Jeanine visited Gym', 0, 7);

        console.log(JSON.stringify({ html, linked, contained, selected, plain }));
        """
    )

    assert values["html"] == (
        'Saw &lt;raw&gt; <token data-target="person:jeanine">Jeanine</token> '
        'at <token data-target="place:gym">Gym</token>.'
    )
    assert values["linked"] == {
        "leading": "  ",
        "label": "Jeanine Peeters",
        "trailing": "  ",
        "target": "person:jeanine_peeters",
        "markdown": "  [Jeanine Peeters](person:jeanine_peeters)  ",
    }
    assert values["contained"] == {
        "start": 4,
        "end": 29,
        "text": "Jeanine",
        "cursor": 11,
    }
    assert values["selected"] == {
        "start": 0,
        "end": 40,
        "text": "Jean and Gym",
        "cursor": 12,
    }
    assert values["plain"] is None


def test_logbook_rich_editor_serializer_preserves_tokens_and_blocks():
    values = _node_eval(
        """
        import { richEditorToMarkdown, tokenPlainText } from './static/js/logbook/editor.js';

        const text = value => ({ nodeType: 3, nodeValue: value });
        const el = (nodeName, childNodes = [], dataset = {}, textContent = '') => ({
          nodeType: 1,
          nodeName,
          childNodes,
          dataset,
          textContent
        });
        const token = (label, target) => el('SPAN', [], { logbookToken: '1', label, target }, label);
        const root = el('DIV', [
          text('Saw\\u00a0'),
          token('Jeanine', 'person:jeanine'),
          el('BR'),
          el('P', [text('At '), token('Gym', 'place:gym')])
        ]);

        console.log(JSON.stringify({
          markdown: richEditorToMarkdown(root),
          fallback: tokenPlainText({ dataset: {}, textContent: '#Office' })
        }));
        """
    )

    assert values == {
        "markdown": "Saw [Jeanine](person:jeanine)\nAt [Gym](place:gym)",
        "fallback": "Office",
    }
