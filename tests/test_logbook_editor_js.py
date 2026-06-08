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
          insertMarkdownHorizontalRule,
          linkedSelectionText,
          renderEditorText,
          toggleMarkdownCodeBlock,
          toggleMarkdownHeading,
          toggleMarkdownLinePrefix,
          toggleMarkdownOrderedList,
          toggleMarkdownSelectionFormat,
          unlinkMarkdownSelection
        } from './static/js/logbook/editor.js';

        const html = renderEditorText(
          '# Title\\nSaw <raw> **bold** and _soft_ `code` ~~gone~~ [Docs](https://example.com/docs) with [Jeanine](person:jeanine) at [Gym](place:gym).\\n- One\\n- Two\\n1. First\\n1. Second\\n> Quote\\n---\\n```\\nblock\\n```',
          {
            escapeHtml: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
            renderLink: (label, target) => target.startsWith('person:') || target.startsWith('place:')
              ? `<token data-target="${target}">${label}</token>`
              : `<a data-href="${target}">${label}</a>`
          }
        );
        const linked = linkedSelectionText('  Jeanine Peeters  ', 'person', (kind, label) => `${kind}:${label.toLowerCase().replaceAll(' ', '_')}`);
        const contained = unlinkMarkdownSelection('Saw [Jeanine](person:jeanine) today', 8, 8);
        const sample = '[Jean](person:jean) and [Gym](place:gym)';
        const selected = unlinkMarkdownSelection(sample, 0, sample.length);
        const plain = unlinkMarkdownSelection('Jeanine visited Gym', 0, 7);
        const rawWrap = toggleMarkdownSelectionFormat('Jeanine visited Gym', 0, 7, '**', '**', 'bold');
        const rawUnwrapInner = toggleMarkdownSelectionFormat('**Jeanine** visited Gym', 2, 9, '**', '**', 'bold');
        const rawUnwrapWhole = toggleMarkdownSelectionFormat('**Jeanine** visited Gym', 0, 11, '**', '**', 'bold');
        const rawUnwrapNestedWhole = toggleMarkdownSelectionFormat('********Jeanine******** visited Gym', 0, 23, '**', '**', 'bold');
        const rawUnwrapNestedInner = toggleMarkdownSelectionFormat('********Jeanine******** visited Gym', 8, 15, '**', '**', 'bold');
        const rawItalicWrap = toggleMarkdownSelectionFormat('Jeanine visited Gym', 0, 7, '_', '_', 'italic', { aliases: [['*', '*']] });
        const rawItalicUnwrapUnderscore = toggleMarkdownSelectionFormat('_Jeanine_ visited Gym', 1, 8, '_', '_', 'italic', { aliases: [['*', '*']] });
        const rawItalicUnwrapStar = toggleMarkdownSelectionFormat('*Jeanine* visited Gym', 1, 8, '_', '_', 'italic', { aliases: [['*', '*']] });
        const rawHeading = toggleMarkdownHeading('Title\\nBody', 2, '## ');
        const rawHeadingOff = toggleMarkdownHeading('## Title\\nBody', 4, '## ');
        const rawQuote = toggleMarkdownLinePrefix('One\\nTwo', 0, 7, '> ');
        const rawQuoteOff = toggleMarkdownLinePrefix('> One\\n> Two', 0, 11, '> ');
        const rawOrdered = toggleMarkdownOrderedList('One\\nTwo', 0, 7);
        const rawOrderedOff = toggleMarkdownOrderedList('1. One\\n2. Two', 0, 13);
        const rawCodeBlock = toggleMarkdownCodeBlock('block', 0, 5);
        const rawCodeBlockOff = toggleMarkdownCodeBlock('```\\nblock\\n```', 0, 13);
        const rawHr = insertMarkdownHorizontalRule('A B', 1, 2);

        console.log(JSON.stringify({
          html,
          linked,
          contained,
          selected,
          plain,
          rawWrap,
          rawUnwrapInner,
          rawUnwrapWhole,
          rawUnwrapNestedWhole,
          rawUnwrapNestedInner,
          rawItalicWrap,
          rawItalicUnwrapUnderscore,
          rawItalicUnwrapStar,
          rawHeading,
          rawHeadingOff,
          rawQuote,
          rawQuoteOff,
          rawOrdered,
          rawOrderedOff,
          rawCodeBlock,
          rawCodeBlockOff,
          rawHr
        }));
        """
    )

    assert values["html"] == (
        '<h1>Title</h1>\n'
        'Saw &lt;raw&gt; <strong>bold</strong> and <em>soft</em> '
        '<code>code</code> <del>gone</del> '
        '<a data-href="https://example.com/docs">Docs</a> with '
        '<token data-target="person:jeanine">Jeanine</token> '
        'at <token data-target="place:gym">Gym</token>.\n'
        '<ul><li>One</li><li>Two</li></ul>\n'
        '<ol><li>First</li><li>Second</li></ol>\n'
        '<blockquote><p>Quote</p></blockquote>\n'
        '<hr>\n'
        '<pre><code>block</code></pre>'
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
    assert values["rawWrap"] == {
        "start": 0,
        "end": 7,
        "text": "**Jeanine**",
        "selectionStart": 2,
        "selectionEnd": 9,
    }
    assert values["rawUnwrapInner"] == {
        "start": 0,
        "end": 11,
        "text": "Jeanine",
        "selectionStart": 0,
        "selectionEnd": 7,
    }
    assert values["rawUnwrapWhole"] == {
        "start": 0,
        "end": 11,
        "text": "Jeanine",
        "selectionStart": 0,
        "selectionEnd": 7,
    }
    assert values["rawUnwrapNestedWhole"] == {
        "start": 0,
        "end": 23,
        "text": "Jeanine",
        "selectionStart": 0,
        "selectionEnd": 7,
    }
    assert values["rawUnwrapNestedInner"] == {
        "start": 0,
        "end": 23,
        "text": "Jeanine",
        "selectionStart": 0,
        "selectionEnd": 7,
    }
    assert values["rawItalicWrap"] == {
        "start": 0,
        "end": 7,
        "text": "_Jeanine_",
        "selectionStart": 1,
        "selectionEnd": 8,
    }
    assert values["rawItalicUnwrapUnderscore"] == {
        "start": 0,
        "end": 9,
        "text": "Jeanine",
        "selectionStart": 0,
        "selectionEnd": 7,
    }
    assert values["rawItalicUnwrapStar"] == {
        "start": 0,
        "end": 9,
        "text": "Jeanine",
        "selectionStart": 0,
        "selectionEnd": 7,
    }
    assert values["rawHeading"]["text"] == "## Title"
    assert values["rawHeadingOff"]["text"] == "Title"
    assert values["rawQuote"]["text"] == "> One\n> Two"
    assert values["rawQuoteOff"]["text"] == "One\nTwo"
    assert values["rawOrdered"]["text"] == "1. One\n2. Two"
    assert values["rawOrderedOff"]["text"] == "One\nTwo"
    assert values["rawCodeBlock"]["text"] == "```\nblock\n```"
    assert values["rawCodeBlockOff"]["text"] == "block"
    assert values["rawHr"]["text"] == "\n---\n"


def test_logbook_rich_editor_serializer_preserves_tokens_and_blocks():
    values = _node_eval(
        """
        import { richEditorToMarkdown, tokenPlainText } from './static/js/logbook/editor.js';

        const text = value => ({ nodeType: 3, nodeValue: value, textContent: value });
        const el = (nodeName, childNodes = [], dataset = {}, textContent = '', attrs = {}) => {
          const node = {
            nodeType: 1,
            nodeName,
            childNodes,
            dataset,
            textContent: textContent || childNodes.map(child => child.textContent || child.nodeValue || '').join(''),
            children: childNodes.filter(child => child.nodeType === 1),
            getAttribute(name) { return attrs[name] || ''; },
            querySelector(selector) {
              return this.children.find(child => child.nodeName.toLowerCase() === selector) || null;
            }
          };
          childNodes.forEach(child => { child.parentNode = node; });
          return node;
        };
        const token = (label, target) => el('SPAN', [], { logbookToken: '1', label, target }, label);
        const root = el('DIV', [
          el('H2', [text('Heading')]),
          text('Saw\\u00a0'),
          el('STRONG', [text('bold')]),
          text(' and '),
          el('STRONG', [el('STRONG', [text('nested')])]),
          text(' and '),
          el('EM', [text('soft')]),
          text(' and '),
          el('DEL', [text('gone')]),
          text(' plus '),
          el('CODE', [text('code')]),
          text(' at '),
          el('A', [text('Docs')], { logbookMarkdownLink: '1', href: 'https://example.com/docs' }, 'Docs', { href: 'https://example.com/docs' }),
          text(' with '),
          token('Jeanine', 'person:jeanine'),
          el('BR'),
          el('P', [text('At '), token('Gym', 'place:gym')]),
          el('UL', [el('LI', [text('One')]), el('LI', [text('Two')])]),
          el('OL', [el('LI', [text('First')]), el('LI', [text('Second')])]),
          el('BLOCKQUOTE', [el('P', [text('Quote')])]),
          el('PRE', [el('CODE', [text('block')])]),
          el('HR')
        ]);

        console.log(JSON.stringify({
          markdown: richEditorToMarkdown(root),
          fallback: tokenPlainText({ dataset: {}, textContent: '#Office' })
        }));
        """
    )

    assert values == {
        "markdown": "## Heading\nSaw **bold** and **nested** and _soft_ and ~~gone~~ plus `code` at [Docs](https://example.com/docs) with [Jeanine](person:jeanine)\nAt [Gym](place:gym)\n- One\n- Two\n1. First\n2. Second\n> Quote\n```\nblock\n```\n---",
        "fallback": "Office",
    }


def test_logbook_rich_editor_token_escape_moves_caret_outside_token():
    values = _node_eval(
        """
        import {
          escapeRichEditorToken,
          richEditorTokenAtCaret
        } from './static/js/logbook/editor.js';

        function wire(parent, nodes) {
          parent.childNodes = nodes;
          nodes.forEach((node, index) => {
            node.parentNode = parent;
            node.parentElement = parent;
            node.previousSibling = nodes[index - 1] || null;
            node.nextSibling = nodes[index + 1] || null;
          });
        }

        const rangeCalls = [];
        const range = {
          startContainer: null,
          startOffset: 0,
          setStart(node, offset) { rangeCalls.push(['setStart', node.name, offset]); },
          setStartAfter(node) { rangeCalls.push(['setStartAfter', node.name]); },
          setStartBefore(node) { rangeCalls.push(['setStartBefore', node.name]); },
          collapse(value) { rangeCalls.push(['collapse', value]); }
        };
        const selection = {
          rangeCount: 0,
          getRangeAt() { return range; },
          removeAllRanges() { rangeCalls.push(['removeAllRanges']); },
          addRange() { rangeCalls.push(['addRange']); }
        };
        const editor = {
          name: 'editor',
          nodeType: 1,
          childNodes: [],
          focusCalled: false,
          ownerDocument: {},
          contains(node) { return node === token || node === nextText || node === secondText; },
          focus() { this.focusCalled = true; },
          insertBefore(node, ref) {
            const index = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
            const next = [...this.childNodes];
            next.splice(index < 0 ? next.length : index, 0, node);
            wire(this, next);
          }
        };
        editor.ownerDocument.createTextNode = value => ({ name: 'inserted', nodeType: 3, nodeValue: value });
        editor.ownerDocument.createRange = () => range;

        const token = {
          name: 'token',
          nodeType: 1,
          dataset: { logbookToken: '1' },
          parentNode: editor,
          parentElement: editor
        };
        const nextText = { name: 'nextText', nodeType: 3, nodeValue: 'after' };
        const secondText = { name: 'secondText', nodeType: 3, nodeValue: ' already' };
        wire(editor, [token, nextText]);

        const activeEscape = escapeRichEditorToken(editor, {
          token,
          selection,
          activeElement: token,
          createTextNode: editor.ownerDocument.createTextNode,
          createRange: editor.ownerDocument.createRange
        });

        wire(editor, [token, secondText]);
        rangeCalls.length = 0;
        const unchangedEscape = escapeRichEditorToken(editor, {
          token,
          selection,
          activeElement: token,
          createTextNode: editor.ownerDocument.createTextNode,
          createRange: editor.ownerDocument.createRange
        });

        selection.rangeCount = 1;
        range.startContainer = editor;
        range.startOffset = 1;
        rangeCalls.length = 0;
        const boundaryToken = richEditorTokenAtCaret(editor, { selection, activeElement: null });
        const boundaryEscape = escapeRichEditorToken(editor, {
          selection,
          activeElement: null,
          ensureSpace: false,
          createTextNode: editor.ownerDocument.createTextNode,
          createRange: editor.ownerDocument.createRange
        });

        console.log(JSON.stringify({
          activeChanged: activeEscape.changed,
          nextText: nextText.nodeValue,
          unchangedChanged: unchangedEscape.changed,
          secondText: secondText.nodeValue,
          boundaryToken: boundaryToken?.name || '',
          boundaryChanged: boundaryEscape.changed,
          boundaryCalls: rangeCalls
        }));
        """
    )

    assert values == {
        "activeChanged": True,
        "nextText": " after",
        "unchangedChanged": False,
        "secondText": " already",
        "boundaryToken": "token",
        "boundaryChanged": False,
        "boundaryCalls": [
            ["setStartAfter", "token"],
            ["collapse", True],
            ["removeAllRanges"],
            ["addRange"],
        ],
    }
