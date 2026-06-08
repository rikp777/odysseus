import { LOGBOOK_LINK_RE, selectionLinkParts } from './entities.js';

function defaultEscape(value) {
  return String(value ?? '');
}

function defaultRenderLink(label, target, { escapeHtml, renderToken } = {}) {
  if (renderToken) return renderToken(label, target);
  const escape = escapeHtml || defaultEscape;
  return escape(label);
}

function renderInlineText(text, { escapeHtml, renderLink, renderToken } = {}) {
  const escape = escapeHtml || defaultEscape;
  const formatterPattern = /(`[^`\n]+`)|\[([^\]\n]{1,300})\]\(([^)\n]{1,700})\)|~~([^~\n]+?)~~|(\*+|_+)([^\n*_]+?)\5/g;
  let html = '';
  let last = 0;
  for (const match of String(text || '').matchAll(formatterPattern)) {
    html += escape(String(text).slice(last, match.index));
    if (match[1]) {
      html += `<code>${escape(match[1].slice(1, -1))}</code>`;
      last = (match.index || 0) + match[0].length;
      continue;
    }
    if (match[2]) {
      html += renderLink
        ? renderLink(match[2], match[3])
        : defaultRenderLink(match[2], match[3], { escapeHtml: escape, renderToken });
      last = (match.index || 0) + match[0].length;
      continue;
    }
    if (match[4]) {
      html += `<del>${escape(match[4])}</del>`;
      last = (match.index || 0) + match[0].length;
      continue;
    }
    const markerSize = match[5].length;
    let formatted = escape(match[6]);
    if (markerSize >= 2) formatted = `<strong>${formatted}</strong>`;
    if (markerSize % 2 === 1) formatted = `<em>${formatted}</em>`;
    html += formatted;
    last = (match.index || 0) + match[0].length;
  }
  html += escape(String(text || '').slice(last));
  return html;
}

function markdownLinkTarget(node) {
  if (!node) return '';
  return node.dataset?.href || node.getAttribute?.('href') || '';
}

function markdownLinkLabel(markdown) {
  return String(markdown || '').replace(/\\/g, '\\\\').replace(/\]/g, '\\]');
}

function markdownLinkUrl(url) {
  return String(url || '').trim().replace(/\)/g, '%29');
}

function inlineCodeValue(value) {
  const text = String(value || '');
  return text.includes('`') ? text.replace(/`/g, '\\`') : text;
}

function blockText(value) {
  return String(value || '').replace(/\n+$/g, '');
}

function clampSelection(value, start, end) {
  const text = String(value || '');
  const rangeStart = Math.max(0, Math.min(Number(start) || 0, text.length));
  const rangeEnd = Math.max(rangeStart, Math.min(Number(end) || rangeStart, text.length));
  return { text, rangeStart, rangeEnd };
}

function repeatedMarkerChar(marker) {
  const value = String(marker || '');
  if (!value || !/^[*_]+$/.test(value)) return '';
  return new Set(value.split('')).size === 1 ? value[0] : '';
}

function markerRunBefore(text, index, marker) {
  const char = repeatedMarkerChar(marker);
  if (!char) return 0;
  let count = 0;
  for (let pos = index - 1; pos >= 0 && text[pos] === char; pos -= 1) count += 1;
  return count;
}

function markerRunAfter(text, index, marker) {
  const char = repeatedMarkerChar(marker);
  if (!char) return 0;
  let count = 0;
  for (let pos = index; pos < text.length && text[pos] === char; pos += 1) count += 1;
  return count;
}

function stripMarkdownFormatLayers(value, prefix, suffix = prefix) {
  let output = String(value || '');
  const leading = String(prefix || '');
  const trailing = String(suffix || '');
  if (!leading || !trailing) return output;

  if (leading.length === 1 && leading === trailing && repeatedMarkerChar(leading)) {
    while (
      output.length >= 2
      && output.startsWith(leading)
      && output.endsWith(trailing)
      && markerRunBefore(output, output.length, trailing) % 2 === 1
      && markerRunAfter(output, 0, leading) % 2 === 1
    ) {
      output = output.slice(leading.length, output.length - trailing.length);
    }
    return output;
  }

  while (
    output.length >= leading.length + trailing.length
    && output.startsWith(leading)
    && output.endsWith(trailing)
  ) {
    output = output.slice(leading.length, output.length - trailing.length);
  }
  return output;
}

function surroundingFormatRange(text, rangeStart, rangeEnd, prefix, suffix = prefix) {
  const leading = String(prefix || '');
  const trailing = String(suffix || '');
  if (!leading || !trailing || rangeStart === rangeEnd) return null;

  let start = rangeStart;
  let end = rangeEnd;
  let expanded = false;

  while (start >= leading.length && end + trailing.length <= text.length) {
    const hasImmediateMarkers = text.slice(start - leading.length, start) === leading
      && text.slice(end, end + trailing.length) === trailing;
    if (!hasImmediateMarkers) break;

    if (leading.length === 1 && leading === trailing && repeatedMarkerChar(leading)) {
      const beforeRun = markerRunBefore(text, start, leading);
      const afterRun = markerRunAfter(text, end, trailing);
      if (beforeRun % 2 !== 1 || afterRun % 2 !== 1) break;
    }

    start -= leading.length;
    end += trailing.length;
    expanded = true;
  }

  return expanded ? { start, end } : null;
}

function closestElement(node) {
  if (!node) return null;
  return node.nodeType === 1 ? node : node.parentElement;
}

function formatTagNames(tagName) {
  const expected = String(tagName || '').toUpperCase();
  if (expected === 'STRONG') return ['STRONG', 'B'];
  if (expected === 'EM') return ['EM', 'I'];
  return expected ? [expected] : [];
}

function nodeMatchesTag(node, tagName) {
  return formatTagNames(tagName).includes(String(node?.nodeName || '').toUpperCase());
}

function closestTagAncestor(node, root, tagName) {
  let current = closestElement(node);
  while (current && current !== root) {
    if (nodeMatchesTag(current, tagName)) return current;
    current = current.parentElement;
  }
  return null;
}

function selectedFormatElement(range, root, tagName) {
  if (
    range?.startContainer
    && range.startContainer === range.endContainer
    && range.startContainer.nodeType === 1
    && range.endOffset === range.startOffset + 1
  ) {
    const child = range.startContainer.childNodes?.[range.startOffset];
    if (
      child?.nodeType === 1
      && nodeMatchesTag(child, tagName)
      && (child === root || root.contains(child))
    ) {
      return child;
    }
  }
  return null;
}

function nodeDepth(node) {
  let depth = 0;
  let current = node;
  while (current?.parentNode) {
    depth += 1;
    current = current.parentNode;
  }
  return depth;
}

function intersectingFormatElements(range, root, tagName) {
  const elements = [];
  const add = node => {
    if (node && node !== root && !elements.includes(node)) elements.push(node);
  };
  add(selectedFormatElement(range, root, tagName));
  add(closestTagAncestor(range.startContainer, root, tagName));
  add(closestTagAncestor(range.endContainer, root, tagName));

  const selector = formatTagNames(tagName).map(name => name.toLowerCase()).join(',');
  if (selector && root?.querySelectorAll) {
    root.querySelectorAll(selector).forEach(node => {
      try {
        if (range.intersectsNode(node)) add(node);
      } catch (_) {
        // Some synthetic ranges throw for detached nodes; ignore those.
      }
    });
  }

  return elements.sort((a, b) => nodeDepth(b) - nodeDepth(a));
}

function unwrapElement(element) {
  if (!element?.parentNode) return null;
  const parent = element.parentNode;
  const moved = [];
  while (element.firstChild) {
    const child = element.firstChild;
    moved.push(child);
    parent.insertBefore(child, element);
  }
  parent.removeChild(element);
  return moved;
}

function uniqueConnectedNodes(nodes) {
  const seen = new Set();
  return (nodes || []).filter(node => {
    if (!node?.parentNode || seen.has(node)) return false;
    seen.add(node);
    return true;
  });
}

export function renderEditorText(content, { escapeHtml, renderToken, renderLink } = {}) {
  const text = String(content || '');
  const escape = escapeHtml || (value => String(value ?? ''));
  const linkRenderer = renderLink
    || ((label, target) => defaultRenderLink(label, target, { escapeHtml: escape, renderToken }));
  const inline = value => renderInlineText(value, { escapeHtml: escape, renderLink: linkRenderer, renderToken });
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const html = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    const fence = line.match(/^```(.*)$/);
    if (fence) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      const language = fence[1]?.trim();
      const cls = language ? ` class="language-${escape(language)}"` : '';
      html.push(`<pre><code${cls}>${escape(codeLines.join('\n'))}</code></pre>`);
      continue;
    }

    if (/^\s*$/.test(line)) {
      html.push('\n');
      continue;
    }

    const hr = line.match(/^\s{0,3}(?:---|\*\*\*|___)\s*$/);
    if (hr) {
      html.push('<hr>');
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      html.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);
      continue;
    }

    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unordered) {
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*[-*+]\s+(.+)$/);
        if (!item) break;
        items.push(`<li>${inline(item[1])}</li>`);
        index += 1;
      }
      index -= 1;
      html.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (ordered) {
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*\d+\.\s+(.+)$/);
        if (!item) break;
        items.push(`<li>${inline(item[1])}</li>`);
        index += 1;
      }
      index -= 1;
      html.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      const parts = [];
      while (index < lines.length) {
        const part = lines[index].match(/^\s*>\s?(.*)$/);
        if (!part) break;
        parts.push(`<p>${inline(part[1])}</p>`);
        index += 1;
      }
      index -= 1;
      html.push(`<blockquote>${parts.join('')}</blockquote>`);
      continue;
    }

    html.push(inline(line));
  }

  return html.join('\n').replace(/\n+$/g, '');
}

export function blockNeedsNewline(el) {
  return el && /^(DIV|P|LI|H[1-6]|BLOCKQUOTE|UL|OL|PRE|HR)$/i.test(el.nodeName || '');
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
  if (node.dataset?.logbookMarkdownLink === '1' || node.nodeName === 'A') {
    const label = Array.from(node.childNodes || [])
      .map(child => serializeRichEditorNode(child, node))
      .join('') || node.textContent || '';
    const target = markdownLinkTarget(node);
    return label && target ? `[${markdownLinkLabel(label)}](${markdownLinkUrl(target)})` : label;
  }
  if (/^(STRONG|B)$/i.test(node.nodeName || '')) {
    const value = stripMarkdownFormatLayers(Array.from(node.childNodes || [])
      .map(child => serializeRichEditorNode(child, node))
      .join(''), '**', '**');
    return value ? `**${value}**` : '';
  }
  if (/^(EM|I)$/i.test(node.nodeName || '')) {
    const value = stripMarkdownFormatLayers(Array.from(node.childNodes || [])
      .map(child => serializeRichEditorNode(child, node))
      .join(''), '_', '_');
    return value ? `_${value}_` : '';
  }
  if (/^(DEL|S|STRIKE)$/i.test(node.nodeName || '')) {
    const value = stripMarkdownFormatLayers(Array.from(node.childNodes || [])
      .map(child => serializeRichEditorNode(child, node))
      .join(''), '~~', '~~');
    return value ? `~~${value}~~` : '';
  }
  if (/^CODE$/i.test(node.nodeName || '') && !/^(PRE)$/i.test(node.parentNode?.nodeName || '')) {
    const value = Array.from(node.childNodes || [])
      .map(child => serializeRichEditorNode(child, node))
      .join('') || node.textContent || '';
    return value ? `\`${inlineCodeValue(value)}\`` : '';
  }
  if (/^PRE$/i.test(node.nodeName || '')) {
    const code = node.querySelector?.('code') || node;
    const value = blockText(code.textContent || '');
    return `\`\`\`\n${value}\n\`\`\`\n`;
  }
  if (/^HR$/i.test(node.nodeName || '')) return '---\n';
  const heading = String(node.nodeName || '').match(/^H([1-6])$/i);
  if (heading) {
    const value = blockText(Array.from(node.childNodes || [])
      .map(child => serializeRichEditorNode(child, node))
      .join(''));
    return value ? `${'#'.repeat(Number(heading[1]))} ${value}\n` : '';
  }
  if (/^UL$/i.test(node.nodeName || '')) {
    return Array.from(node.children || [])
      .filter(child => /^LI$/i.test(child.nodeName || ''))
      .map(child => `- ${blockText(serializeRichEditorNode(child, node))}`)
      .join('\n') + '\n';
  }
  if (/^OL$/i.test(node.nodeName || '')) {
    return Array.from(node.children || [])
      .filter(child => /^LI$/i.test(child.nodeName || ''))
      .map((child, index) => `${index + 1}. ${blockText(serializeRichEditorNode(child, node))}`)
      .join('\n') + '\n';
  }
  if (/^BLOCKQUOTE$/i.test(node.nodeName || '')) {
    const value = blockText(Array.from(node.childNodes || [])
      .map(child => serializeRichEditorNode(child, node))
      .join(''));
    return value ? `${value.split('\n').map(line => `> ${line}`).join('\n')}\n` : '';
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

export function toggleMarkdownSelectionFormat(value, start, end, prefix, suffix = prefix, placeholder = 'text', options = {}) {
  const { text, rangeStart, rangeEnd } = clampSelection(value, start, end);
  const leading = String(prefix || '');
  const trailing = String(suffix || '');
  if (!leading || !trailing) return null;
  const selected = text.slice(rangeStart, rangeEnd);
  const aliases = Array.isArray(options?.aliases) ? options.aliases : [];
  const markers = [[leading, trailing], ...aliases]
    .map(([startMarker, endMarker = startMarker]) => [String(startMarker || ''), String(endMarker || '')])
    .filter(([startMarker, endMarker]) => startMarker && endMarker);

  for (const [startMarker, endMarker] of markers) {
    const unwrappedSelected = stripMarkdownFormatLayers(selected, startMarker, endMarker);
    if (selected && unwrappedSelected !== selected) {
      return {
        start: rangeStart,
        end: rangeEnd,
        text: unwrappedSelected,
        selectionStart: rangeStart,
        selectionEnd: rangeStart + unwrappedSelected.length,
      };
    }

    const wrappedRange = surroundingFormatRange(text, rangeStart, rangeEnd, startMarker, endMarker);
    if (wrappedRange) {
      return {
        start: wrappedRange.start,
        end: wrappedRange.end,
        text: selected,
        selectionStart: wrappedRange.start,
        selectionEnd: wrappedRange.start + selected.length,
      };
    }
  }

  const selectedOrPlaceholder = selected || String(placeholder || 'text');
  const wrapped = `${leading}${selectedOrPlaceholder}${trailing}`;
  return {
    start: rangeStart,
    end: rangeEnd,
    text: wrapped,
    selectionStart: rangeStart + leading.length,
    selectionEnd: rangeStart + leading.length + selectedOrPlaceholder.length,
  };
}

function selectedLineRange(text, start, end) {
  const lineStart = text.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
  const nextBreak = text.indexOf('\n', end);
  const lineEnd = nextBreak === -1 ? text.length : nextBreak;
  return { lineStart, lineEnd };
}

export function toggleMarkdownHeading(value, caret, prefix) {
  const { text, rangeStart } = clampSelection(value, caret, caret);
  const marker = String(prefix || '');
  if (!marker) return null;
  const { lineStart, lineEnd } = selectedLineRange(text, rangeStart, rangeStart);
  const line = text.slice(lineStart, lineEnd);
  const existing = line.match(/^(#{1,6})\s+/);
  const nextLine = existing && existing[1].length === marker.trim().length
    ? line.slice(existing[0].length)
    : `${marker}${existing ? line.slice(existing[0].length) : line}`;
  const delta = nextLine.length - line.length;
  const cursor = Math.max(lineStart, rangeStart + delta);
  return {
    start: lineStart,
    end: lineEnd,
    text: nextLine,
    selectionStart: cursor,
    selectionEnd: cursor,
  };
}

export function toggleMarkdownLinePrefix(value, start, end, prefix) {
  const { text, rangeStart, rangeEnd } = clampSelection(value, start, end);
  const marker = String(prefix || '');
  if (!marker) return null;
  const { lineStart, lineEnd } = selectedLineRange(text, rangeStart, rangeEnd);
  const block = text.slice(lineStart, lineEnd);
  const lines = block.split('\n');
  const nonEmpty = lines.filter(line => line.trim());
  const allPrefixed = nonEmpty.length > 0 && nonEmpty.every(line => line.startsWith(marker));
  const next = lines.map(line => {
    if (!line.trim()) return line;
    return allPrefixed && line.startsWith(marker) ? line.slice(marker.length) : `${marker}${line}`;
  }).join('\n');
  return {
    start: lineStart,
    end: lineEnd,
    text: next,
    selectionStart: lineStart,
    selectionEnd: lineStart + next.length,
  };
}

export function toggleMarkdownOrderedList(value, start, end) {
  const { text, rangeStart, rangeEnd } = clampSelection(value, start, end);
  const { lineStart, lineEnd } = selectedLineRange(text, rangeStart, rangeEnd);
  const block = text.slice(lineStart, lineEnd);
  const lines = block.split('\n');
  const nonEmpty = lines.filter(line => line.trim());
  const allNumbered = nonEmpty.length > 0 && nonEmpty.every(line => /^\d+\.\s+/.test(line));
  let number = 0;
  const next = lines.map(line => {
    if (!line.trim()) return line;
    return allNumbered ? line.replace(/^\d+\.\s+/, '') : `${++number}. ${line}`;
  }).join('\n');
  return {
    start: lineStart,
    end: lineEnd,
    text: next,
    selectionStart: lineStart,
    selectionEnd: lineStart + next.length,
  };
}

export function toggleMarkdownCodeBlock(value, start, end) {
  const { text, rangeStart, rangeEnd } = clampSelection(value, start, end);
  const selected = text.slice(rangeStart, rangeEnd);
  const selectedMatch = selected.match(/^```\n([\s\S]*?)\n```$/);
  if (selectedMatch) {
    return {
      start: rangeStart,
      end: rangeEnd,
      text: selectedMatch[1],
      selectionStart: rangeStart,
      selectionEnd: rangeStart + selectedMatch[1].length,
    };
  }

  const wrapped = `\`\`\`\n${selected || 'code'}\n\`\`\``;
  return {
    start: rangeStart,
    end: rangeEnd,
    text: wrapped,
    selectionStart: rangeStart + 4,
    selectionEnd: rangeStart + 4 + (selected || 'code').length,
  };
}

export function insertMarkdownHorizontalRule(value, start, end) {
  const { text, rangeStart, rangeEnd } = clampSelection(value, start, end);
  const before = rangeStart > 0 && text[rangeStart - 1] !== '\n' ? '\n' : '';
  const replacement = `${before}---\n`;
  const cursor = rangeStart + replacement.length;
  return {
    start: rangeStart,
    end: rangeEnd,
    text: replacement,
    selectionStart: cursor,
    selectionEnd: cursor,
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

function closestRichEditorToken(node, editor) {
  let current = closestElement(node);
  while (current && current !== editor) {
    if (current.dataset?.logbookToken === '1') return current;
    current = current.parentElement;
  }
  return null;
}

function boundaryToken(container, offset, editor) {
  if (!container || !editor) return null;
  if (container.nodeType === 1) {
    const before = offset > 0 ? container.childNodes?.[offset - 1] : null;
    const after = container.childNodes?.[offset] || null;
    if (before?.dataset?.logbookToken === '1') return before;
    if (after?.dataset?.logbookToken === '1') return after;
  }
  return null;
}

export function richEditorTokenAtCaret(editor, {
  selection = globalThis.window?.getSelection?.(),
  activeElement = globalThis.document?.activeElement,
} = {}) {
  if (!editor) return null;
  const activeToken = closestRichEditorToken(activeElement, editor);
  if (activeToken && editor.contains(activeToken)) return activeToken;
  if (!selection || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
  if (!startsInside) return null;
  return closestRichEditorToken(range.startContainer, editor)
    || boundaryToken(range.startContainer, range.startOffset, editor);
}

export function escapeRichEditorToken(editor, {
  token = null,
  side = 'after',
  ensureSpace = true,
  selection = globalThis.window?.getSelection?.(),
  activeElement = globalThis.document?.activeElement,
  createTextNode = text => (editor?.ownerDocument || globalThis.document)?.createTextNode?.(text),
  createRange = () => (editor?.ownerDocument || globalThis.document)?.createRange?.(),
} = {}) {
  if (!editor || !selection) return null;
  const resolvedToken = token && editor.contains(token) && token.dataset?.logbookToken === '1'
    ? token
    : richEditorTokenAtCaret(editor, { selection, activeElement });
  if (!resolvedToken?.parentNode) return null;

  const range = createRange();
  if (!range) return null;
  let changed = false;

  if (side === 'before') {
    range.setStartBefore(resolvedToken);
  } else if (ensureSpace) {
    const next = resolvedToken.nextSibling;
    if (next?.nodeType === 3) {
      if (!/^[\s\u00a0]/.test(next.nodeValue || '')) {
        next.nodeValue = ` ${next.nodeValue || ''}`;
        changed = true;
      }
      range.setStart(next, 1);
    } else {
      const space = createTextNode(' ');
      if (!space) return null;
      resolvedToken.parentNode.insertBefore(space, next || null);
      changed = true;
      range.setStart(space, 1);
    }
  } else {
    range.setStartAfter(resolvedToken);
  }

  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
  editor.focus?.();
  return { token: resolvedToken, changed };
}

export function wrapRichSelection(editor, tagName, {
  attrs = {},
  selection = globalThis.window?.getSelection?.(),
  createElement = name => (editor?.ownerDocument || globalThis.document)?.createElement?.(name),
} = {}) {
  if (!editor || !tagName || !selection || !selection.rangeCount) return false;
  const range = selection.getRangeAt(0);
  const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
  const endsInside = range.endContainer === editor || editor.contains(range.endContainer);
  if (range.collapsed || !startsInside || !endsInside || !selection.toString().trim()) return false;

  const wrapper = createElement(tagName);
  if (!wrapper) return false;
  Object.entries(attrs || {}).forEach(([name, value]) => {
    if (value !== null && value !== undefined) wrapper.setAttribute(name, String(value));
  });
  wrapper.appendChild(range.extractContents());
  range.insertNode(wrapper);
  range.setStartAfter(wrapper);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
  editor.focus();
  return true;
}

export function toggleRichSelectionFormat(editor, tagName, {
  attrs = {},
  selection = globalThis.window?.getSelection?.(),
  createRange = () => (editor?.ownerDocument || globalThis.document)?.createRange?.(),
} = {}) {
  if (!editor || !tagName || !selection || !selection.rangeCount) return false;
  const range = selection.getRangeAt(0);
  const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
  const endsInside = range.endContainer === editor || editor.contains(range.endContainer);
  if (range.collapsed || !startsInside || !endsInside || !selection.toString().trim()) return false;

  const existingFormats = intersectingFormatElements(range, editor, tagName);
  if (existingFormats.length) {
    const moved = existingFormats.flatMap(element => unwrapElement(element) || []);
    const selectedNodes = uniqueConnectedNodes(moved);
    if (!selectedNodes.length) return false;
    const nextRange = createRange();
    if (nextRange) {
      nextRange.setStartBefore(selectedNodes[0]);
      nextRange.setEndAfter(selectedNodes[selectedNodes.length - 1]);
      selection.removeAllRanges();
      selection.addRange(nextRange);
    }
    editor.focus();
    return true;
  }

  return wrapRichSelection(editor, tagName, { attrs, selection });
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
