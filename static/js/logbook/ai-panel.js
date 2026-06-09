export const AI_MODE_GROUPS = [
  {
    label: 'Write',
    items: [
      { mode: 'structure_day', label: 'Draft', detail: 'Shape today', icon: 'book', primary: true },
      { mode: 'clean_spelling', label: 'Spelling', detail: 'Keep voice', icon: 'bold' },
      { mode: 'ask_questions', label: 'Questions', detail: 'Find gaps', icon: 'quote' },
    ],
  },
  {
    label: 'Review',
    items: [
      { mode: 'summarize', label: 'Summary', detail: 'Short recap', icon: 'list' },
      { mode: 'reflect', label: 'Reflect', detail: 'Gentle note', icon: 'quote' },
    ],
  },
  {
    label: 'Extract',
    items: [
      { mode: 'extract_people', label: 'People', detail: 'Mentions', icon: 'person' },
      { mode: 'extract_locations', label: 'Places', detail: 'Locations', icon: 'location' },
      { mode: 'extract_all', label: 'Detect', detail: 'Links and data', icon: 'link' },
      { mode: 'extract_facts', label: 'Facts', detail: 'Saved entry', icon: 'food', facts: true },
    ],
  },
];

function fallbackEscapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function aiModeMeta(mode, groups = AI_MODE_GROUPS) {
  for (const group of groups) {
    const found = group.items.find(item => item.mode === mode);
    if (found) return found;
  }
  return { mode, label: String(mode || '').replace(/_/g, ' '), detail: '', icon: 'person' };
}

function metricHtml(label, value, meta, escapeHtml) {
  return `
    <div class="logbook-ai-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${meta ? `<em>${escapeHtml(meta)}</em>` : ''}
    </div>
  `;
}

function usageMeterHtml(context) {
  const {
    actual,
    entryContent,
    estimate,
    estimateBusy,
    estimateEntryTokens,
    escapeHtml,
    formatCompactTokens,
    formatMoneyDisplay,
    usage,
  } = context;
  const billing = usage.billing || {};
  const day = usage.day || {};
  const month = usage.month || {};
  const estimatedInput = estimate?.input_tokens ?? estimateEntryTokens(entryContent || '');
  const estimatedOutput = estimate?.max_output_tokens ?? 0;
  const estimatedTotal = estimate?.total_tokens ?? (estimatedInput + estimatedOutput);
  const estimateCost = estimate?.cost || {};
  const runCost = billing.enabled
    ? formatMoneyDisplay(estimateCost.display, estimateCost.known ? '$0.00' : 'Unknown')
    : 'Billing off';
  const billingLabel = billing.enabled
    ? (billing.usage_ledger_enabled === false ? 'Billing on, ledger off' : 'Billing on')
    : 'Billing off';
  const dayCost = billing.enabled ? formatMoneyDisplay(day.display, '$0.00') : '';
  const monthCost = billing.enabled ? formatMoneyDisplay(month.display, '$0.00') : '';
  const actualMeta = actual?.total_tokens
    ? `${formatCompactTokens(actual.total_tokens)} last run${actual.cost?.display && billing.enabled ? ` | ${actual.cost.display}` : ''}`
    : (estimateBusy ? 'Updating...' : 'Ready');
  return `
    <div class="logbook-ai-meter">
      <div class="logbook-ai-meter-head">
        <span>Usage</span>
        <strong>${escapeHtml(billingLabel)}</strong>
      </div>
      <div class="logbook-ai-meter-grid">
        ${metricHtml('Prompt', formatCompactTokens(estimatedInput), 'input', escapeHtml)}
        ${metricHtml('Output cap', estimatedOutput ? formatCompactTokens(estimatedOutput) : '0', 'max', escapeHtml)}
        ${metricHtml('Run total', formatCompactTokens(estimatedTotal), actualMeta, escapeHtml)}
        ${metricHtml('Run cost', runCost, estimateCost.known || !billing.enabled ? '' : 'pricing missing', escapeHtml)}
      </div>
      <div class="logbook-ai-ledger">
        <span><strong>Today</strong>${escapeHtml(formatCompactTokens(day.total_tokens || 0))} tokens${dayCost ? ` | ${escapeHtml(dayCost)}` : ''}</span>
        <span><strong>Month</strong>${escapeHtml(formatCompactTokens(month.total_tokens || 0))} tokens${monthCost ? ` | ${escapeHtml(monthCost)}` : ''}</span>
      </div>
    </div>
  `;
}

function modeGroupsHtml(context, disabled, disabledTitle) {
  const { escapeHtml, icon, modeGroups, selectedMode } = context;
  return modeGroups.map(group => `
    <div class="logbook-ai-command-group">
      <div class="logbook-ai-command-title">${escapeHtml(group.label)}</div>
      <div class="logbook-ai-command-grid">
        ${group.items.map(item => {
          const active = selectedMode === item.mode;
          const primary = item.primary ? ' primary' : '';
          const activeCls = active ? ' active' : '';
          return `
            <button type="button" class="logbook-ai-command${primary}${activeCls}" data-ai-mode="${escapeHtml(item.mode)}"${disabled}${disabledTitle}>
              <span class="logbook-ai-command-icon">${icon(item.icon, 14)}</span>
              <span class="logbook-ai-command-copy">
                <strong>${escapeHtml(item.label)}</strong>
                <em>${escapeHtml(item.detail)}</em>
              </span>
            </button>
          `;
        }).join('')}
      </div>
    </div>
  `).join('');
}

function runControlsHtml(context, disabled, disabledTitle) {
  const { escapeHtml, modeGroups, selectedMode } = context;
  const selected = aiModeMeta(selectedMode, modeGroups);
  const isFactsMode = selectedMode === 'extract_facts';
  const label = isFactsMode ? 'Run fact extraction' : 'Run AI help';
  const detail = isFactsMode ? 'Uses the saved entry' : `${selected.label} | ${selected.detail}`;
  return `
    <div class="logbook-ai-runbar">
      <div class="logbook-ai-runbar-copy">
        <span>Selected</span>
        <strong>${escapeHtml(selected.label)}</strong>
        <em>${escapeHtml(detail)}</em>
      </div>
      <button type="button" class="cal-btn cal-btn-primary logbook-ai-run-btn" id="logbook-run-ai"${disabled}${disabledTitle}>${escapeHtml(label)}</button>
    </div>
  `;
}

function runReceiptHtml(context) {
  const { escapeHtml, formatCompactTokens, formatMoneyDisplay, modeGroups, preview, selectedMode } = context;
  const usage = preview?.usage;
  if (!usage) return '';
  const actual = usage.actual || {};
  const billing = usage.billing || {};
  const mode = aiModeMeta(usage.mode || selectedMode, modeGroups);
  const state = usage.fallback ? 'Local fallback' : usage.cached ? 'Cached result' : 'Last run';
  const cost = billing.enabled
    ? formatMoneyDisplay(actual.cost?.display, actual.cost?.known ? '$0.00' : 'Unknown cost')
    : 'Billing off';
  const source = actual.usage_source ? ` | ${actual.usage_source}` : '';
  return `
    <div class="logbook-ai-receipt">
      <div>
        <strong>${escapeHtml(state)}</strong>
        <span>${escapeHtml(mode.label)}${escapeHtml(source)}</span>
      </div>
      <div>
        <strong>${escapeHtml(formatCompactTokens(actual.total_tokens || 0))}</strong>
        <span>${escapeHtml(cost)}</span>
      </div>
    </div>
  `;
}

function previewHtml(context) {
  const {
    escapeHtml,
    personSuggestionActionLabel,
    personSuggestionMeta,
    preview,
    renderLogbookText,
  } = context;
  const p = preview || {};
  const warning = p.warning ? `<div class="logbook-ai-warning">${escapeHtml(p.warning)}</div>` : '';
  const questions = (p.questions || []).map(q => `<li>${escapeHtml(q)}</li>`).join('');
  const data = (p.datapoint_suggestions || []).map(d => `
    <div class="logbook-suggestion-row">
      <strong>${escapeHtml(d.label || d.key || 'Data')}</strong>
      <span>${escapeHtml(d.value_text || d.value_number || '')}${d.unit ? ` ${escapeHtml(d.unit)}` : ''}</span>
    </div>
  `).join('');
  const people = (p.people_suggestions || []).map((person, index) => `
    <div class="logbook-suggestion-row">
      <strong>${escapeHtml(person.display_name || person.surface_text || 'Person')}</strong>
      <span>${escapeHtml(personSuggestionMeta(person))}</span>
      <button type="button" class="cal-btn" data-add-ai-person="${index}">${escapeHtml(personSuggestionActionLabel(person))}</button>
    </div>
  `).join('');
  const locations = (p.location_suggestions || []).map((loc, index) => `
    <div class="logbook-suggestion-row">
      <strong>${escapeHtml(loc.display_name || loc.surface_text || 'Place')}</strong>
      <span>${escapeHtml(loc.reason || 'Suggested from entry')}</span>
      <button type="button" class="cal-btn" data-add-ai-location="${index}">Add</button>
    </div>
  `).join('');
  const connections = (p.connection_suggestions || []).map(c => `
    <div class="logbook-suggestion-row">
      <strong>${escapeHtml(c.person_a || 'Person')} + ${escapeHtml(c.person_b || 'Person')}</strong>
      <span>${escapeHtml(c.description || c.connection_type || 'Possible connection')}</span>
    </div>
  `).join('');
  return `
    ${warning}
    ${p.preview_content ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Preview</div><div class="logbook-rendered-text">${renderLogbookText(p.preview_content)}</div></div>` : ''}
    ${p.summary ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Summary</div><p>${escapeHtml(p.summary)}</p></div>` : ''}
    ${p.reflection ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Reflection</div><p>${escapeHtml(p.reflection)}</p></div>` : ''}
    ${questions ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Questions</div><ul>${questions}</ul></div>` : ''}
    ${p.mood_suggestion ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Mood</div><p>${escapeHtml(p.mood_suggestion.label || '')} ${p.mood_suggestion.score ? `(${escapeHtml(p.mood_suggestion.score)})` : ''}</p><button type="button" class="cal-btn" id="logbook-apply-ai-mood">Use mood</button></div>` : ''}
    ${data ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Data suggestions</div>${data}<button type="button" class="cal-btn" id="logbook-add-ai-data">Add data</button></div>` : ''}
    ${people ? `<div class="logbook-preview-block"><div class="logbook-subtitle">People suggestions</div>${people}</div>` : ''}
    ${locations ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Place suggestions</div>${locations}</div>` : ''}
    ${connections ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Connection suggestions</div>${connections}</div>` : ''}
    <div class="logbook-preview-actions">
      ${p.preview_content ? '<button type="button" class="cal-btn cal-btn-primary" id="logbook-apply-ai">Apply</button>' : ''}
      <button type="button" class="cal-btn" id="logbook-copy-ai">Copy</button>
      <button type="button" class="cal-btn" id="logbook-clear-ai">Cancel</button>
    </div>
  `;
}

export function renderAIPanelHtml(options = {}) {
  const context = {
    actual: options.actual || null,
    aiStatus: options.aiStatus || null,
    busy: Boolean(options.busy),
    entryContent: options.entryContent || '',
    error: options.error || '',
    escapeHtml: options.escapeHtml || fallbackEscapeHtml,
    estimate: options.estimate || null,
    estimateBusy: Boolean(options.estimateBusy),
    estimateEntryTokens: options.estimateEntryTokens || (() => 0),
    formatCompactTokens: options.formatCompactTokens || (value => String(value || 0)),
    formatMoneyDisplay: options.formatMoneyDisplay || ((display, fallback) => display || fallback || ''),
    icon: options.icon || (() => ''),
    modeGroups: options.modeGroups || AI_MODE_GROUPS,
    personSuggestionActionLabel: options.personSuggestionActionLabel || (() => 'Add'),
    personSuggestionMeta: options.personSuggestionMeta || (() => ''),
    preview: options.preview || null,
    renderLogbookText: options.renderLogbookText || fallbackEscapeHtml,
    selectedMode: options.selectedMode || 'structure_day',
    usage: options.usage || {},
  };
  const aiAvailable = context.aiStatus?.available === true;
  const disabled = aiAvailable ? '' : ' disabled aria-disabled="true"';
  const disabledTitle = aiAvailable ? '' : ` title="${context.escapeHtml(context.aiStatus?.reason || 'No LLM provider configured')}"`;
  const preview = context.preview
    ? previewHtml(context)
    : aiAvailable
      ? '<div class="logbook-empty">AI previews appear here.</div>'
      : '<div class="logbook-empty">Manual writing still works. Configure a default or utility LLM provider to enable AI help.</div>';
  return `
    <div class="logbook-section-head logbook-ai-head">
      <h5>AI help</h5>
      ${aiAvailable ? `<span class="logbook-ai-model" title="${context.escapeHtml(context.aiStatus.model || '')}">${context.escapeHtml(context.aiStatus.model || 'AI ready')}</span>` : ''}
    </div>
    <div class="logbook-ai-control-box">
      ${aiAvailable ? usageMeterHtml(context) : `<div class="logbook-ai-disabled">AI help is off: ${context.escapeHtml(context.aiStatus?.reason || 'No LLM provider configured')}.</div>`}
      <div class="logbook-ai-actions">${modeGroupsHtml(context, disabled, disabledTitle)}</div>
      ${aiAvailable ? runControlsHtml(context, disabled, disabledTitle) : ''}
      ${context.busy ? '<div class="logbook-ai-status">Thinking...</div>' : ''}
      ${context.error ? `<div class="logbook-ai-error">${context.escapeHtml(context.error)}</div>` : ''}
    </div>
    <section class="logbook-ai-results" aria-label="AI results">
      <div class="logbook-section-head"><h5>Results</h5></div>
      ${runReceiptHtml(context)}
      <div id="logbook-ai-preview" class="logbook-ai-preview">${preview}</div>
    </section>
  `;
}

function runHandler(handler, onError) {
  try {
    const result = handler?.();
    if (result && typeof result.catch === 'function') result.catch(onError);
  } catch (err) {
    onError(err);
  }
}

export function bindAIPanelEvents(root = document, handlers = {}) {
  const onError = handlers.onError || (() => {});
  const selectedMode = () => (
    typeof handlers.selectedMode === 'function'
      ? handlers.selectedMode()
      : (handlers.selectedMode || 'structure_day')
  );

  root.querySelectorAll('[data-ai-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.aiMode || 'structure_day';
      handlers.selectMode?.(mode);
    });
  });
  root.querySelector('#logbook-run-ai')?.addEventListener('click', () => {
    const mode = selectedMode();
    if (mode === 'extract_facts') runHandler(() => handlers.extractFacts?.(), onError);
    else runHandler(() => handlers.runAI?.(mode), onError);
  });
  root.querySelector('#logbook-extract-facts')?.addEventListener('click', () => runHandler(() => handlers.extractFacts?.(), onError));
  root.querySelector('#logbook-apply-ai')?.addEventListener('click', () => handlers.applyContent?.());
  root.querySelector('#logbook-copy-ai')?.addEventListener('click', () => handlers.copyAI?.());
  root.querySelector('#logbook-clear-ai')?.addEventListener('click', () => handlers.clearAI?.());
  root.querySelector('#logbook-apply-ai-mood')?.addEventListener('click', () => handlers.applyMood?.());
  root.querySelector('#logbook-add-ai-data')?.addEventListener('click', () => handlers.addData?.());
  handlers.bindSuggestions?.(root);
  handlers.bindEntityLinks?.(root);
}
