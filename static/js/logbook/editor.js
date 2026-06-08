import { LOGBOOK_LINK_RE, selectionLinkParts } from './entities.js';

function defaultEscape(value) {
  return String(value ?? '');
}

export function renderEditorText(content, { escapeHtml, renderToken, linkPattern = LOGBOOK_LINK_RE } = {}) {
  const text = String(content || '');
  const escape = escapeHtml || (value => String(value ?? ''));
  const token = renderToken || ((label) => escape(label));
  let html = '';
  let last = 0;
  linkPattern.lastIndex = 0;
  for (const match of text.matchAll(linkPattern)) {
    html += escape(text.slice(last, match.index));
    html += token(match[1], match[2]);
    last = match.index + match[0].length;
  }
  html += escape(text.slice(last));
  return html;
}

export function blockNeedsNewline(el) {
  return el && /^(DIV|P|LI|H[1-6]|BLOCKQUOTE)$/i.test(el.nodeName || '');
}

export function tokenPlainText(token) {
  const label = token?.dataset?.label || '';
  if (label) return label;
  return String(token?.textContent || '').replace(/^[@#]/, '');
}

export function serializeRichEditorNode(node, root) {
  if (!node) return '';
  if (node.nodeType === 3) return node.nodeValue.replace(/\u00a0/g, ' ');
  if (node.nodeType !== 1) return '';
  if (node.dataset?.logbookToken === '1') {
    const label = node.dataset.label || tokenPlainText(node).trim();
    const target = node.dataset.target || '';
    return label && target ? `[${label}](${target})` : node.textContent || '';
  }
  if (node.nodeName === 'BR') return '\n';
  let out = '';
  Array.from(node.childNodes || []).forEach(child => { out += serializeRichEditorNode(child, root); });
  if (node !== root && blockNeedsNewline(node) && out && !out.endsWith('\n')) out += '\n';
  return out;
}

export function richEditorToMarkdown(editor) {
  if (!editor) return '';
  return serializeRichEditorNode(editor, editor)
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]+\n/g, '\n')
    .trimEnd();
}

export function linkedSelectionText(text, kind, resolveTarget) {
  const parts = selectionLinkParts(text);
  if (!parts) return null;
  const target = resolveTarget(kind, parts.label);
  return {
    ...parts,
    target,
    markdown: `${parts.leading}[${parts.label}](${target})${parts.trailing}`,
  };
}

export function unlinkMarkdownSelection(value, start, end, linkPattern = LOGBOOK_LINK_RE) {
  const text = String(value || '');
  const rangeStart = Math.max(0, Number(start) || 0);
  const rangeEnd = Math.max(rangeStart, Number(end) || rangeStart);

  linkPattern.lastIndex = 0;
  for (const match of text.matchAll(linkPattern)) {
    const matchStart = match.index ?? 0;
    const matchEnd = matchStart + match[0].length;
    if (matchStart <= rangeStart && matchEnd >= rangeEnd) {
      return {
        start: matchStart,
        end: matchEnd,
        text: match[1],
        cursor: matchStart + match[1].length,
      };
    }
  }

  if (rangeStart === rangeEnd) return null;
  const selected = text.slice(rangeStart, rangeEnd);
  linkPattern.lastIndex = 0;
  const unlinked = selected.replace(linkPattern, '$1');
  if (unlinked === selected) return null;
  return {
    start: rangeStart,
    end: rangeEnd,
    text: unlinked,
    cursor: rangeStart + unlinked.length,
  };
}

export function replaceRichSelectionWithLink(editor, kind, {
  selection = globalThis.window?.getSelection?.(),
  resolveTarget,
  renderToken,
  escapeHtml = defaultEscape,
  createTemplate = html => {
    const documentRef = editor?.ownerDocument || globalThis.document;
    const template = documentRef?.createElement?.('template');
    if (!template) return null;
    template.innerHTML = html;
    return template;
  },
} = {}) {
  if (!editor || !selection || !selection.rangeCount || !resolveTarget || !renderToken) return false;
  const range = selection.getRangeAt(0);
  const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
  const endsInside = range.endContainer === editor || editor.contains(range.endContainer);
  if (range.collapsed || !startsInside || !endsInside) return false;

  const linked = linkedSelectionText(selection.toString(), kind, resolveTarget);
  if (!linked) return false;
  const template = createTemplate(
    `${escapeHtml(linked.leading)}${renderToken(linked.label, linked.target)}${escapeHtml(linked.trailing)}`,
  );
  if (!template) return false;

  const fragment = template.content;
  const last = fragment.lastChild;
  range.deleteContents();
  range.insertNode(fragment);
  if (last) {
    range.setStartAfter(last);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
  }
  editor.focus();
  return true;
}

export function unlinkRichSelection(editor, {
  selection = globalThis.window?.getSelection?.(),
  activeElement = globalThis.document?.activeElement,
  createTextNode = text => (editor?.ownerDocument || globalThis.document)?.createTextNode?.(text),
  createRange = () => (editor?.ownerDocument || globalThis.document)?.createRange?.(),
} = {}) {
  if (!editor) return false;
  const activeToken = activeElement?.dataset?.logbookToken === '1' && editor.contains(activeElement)
    ? activeElement
    : null;
  let tokens = activeToken ? [activeToken] : [];
  if (!tokens.length && selection?.rangeCount) {
    const range = selection.getRangeAt(0);
    const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
    const endsInside = range.endContainer === editor || editor.contains(range.endContainer);
    if (startsInside && endsInside) {
      tokens = [...editor.querySelectorAll('[data-logbook-token="1"]')]
        .filter(token => {
          try {
            return range.intersectsNode(token);
          } catch (_) {
            return false;
          }
        });
    }
  }
  if (!tokens.length) return false;

  let last = null;
  for (const token of tokens) {
    const textNode = createTextNode(tokenPlainText(token));
    if (!textNode) return false;
    token.replaceWith(textNode);
    last = textNode;
  }
  if (last && selection) {
    const range = createRange();
    if (range) {
      range.setStartAfter(last);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }
  editor.focus();
  return true;
}

export function selectionInside(el, selection = globalThis.window?.getSelection?.()) {
  if (!selection || !selection.rangeCount || !el) return false;
  const node = selection.anchorNode;
  return Boolean(node && (node === el || el.contains(node)));
}

export function focusRichEditorEnd(
  editor,
  selection = globalThis.window?.getSelection?.(),
  createRange = () => globalThis.document?.createRange?.(),
) {
  if (!editor) return;
  editor.focus();
  const range = createRange();
  if (!range) return;
  range.selectNodeContents(editor);
  range.collapse(false);
  selection?.removeAllRanges();
  selection?.addRange(range);
}
