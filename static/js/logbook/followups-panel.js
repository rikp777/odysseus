import { logbookIcon } from './icons.js';
import { escapeHtml as _e } from './utils.js';

function contactText(methods = []) {
  if (!methods.length) return 'No linked contact';
  return methods.slice(0, 2).map(item => `${item.type || 'contact'}: ${item.value || ''}`).join(' | ');
}

function statusText(item) {
  if (item.status === 'snoozed') return `Snoozed until ${item.suppression?.until || ''}`.trim();
  if (item.status === 'dismissed') return 'Dismissed';
  if (item.level === 'overdue') return 'Overdue';
  if (item.level === 'due') return 'Due';
  return 'Soft';
}

function connectionText(item) {
  const accepted = Number(item.accepted_connections || 0);
  const suggested = Number(item.suggested_connections || 0);
  const bits = [];
  if (accepted) bits.push(`${accepted} accepted`);
  if (suggested) bits.push(`${suggested} suggested`);
  return bits.join(' | ');
}

function followupCardHtml(item) {
  const personId = item.id || item.person?.id || '';
  const meta = [
    item.last_mentioned ? `last ${item.last_mentioned}` : '',
    item.days_since_mentioned ? `${item.days_since_mentioned} days` : '',
    item.relationship_label || '',
    contactText(item.contact_methods || []),
    connectionText(item),
  ].filter(Boolean).join(' | ');
  const active = item.status === 'active';
  return `
    <div class="logbook-followup-card ${_e(item.status || 'active')}" data-level="${_e(item.level || 'soft')}">
      <div class="logbook-followup-head">
        <strong>${logbookIcon('person', 12)}${_e(item.display_name || item.person?.display_name || 'Person')}</strong>
        <span>${_e(statusText(item))}</span>
      </div>
      <p>${_e(item.message || item.reason || '')}</p>
      ${meta ? `<div class="logbook-followup-meta">${_e(meta)}</div>` : ''}
      <div class="logbook-followup-actions">
        <button type="button" class="cal-btn" data-followup-open="${_e(personId)}">Open</button>
        ${active ? `<button type="button" class="cal-btn" data-followup-snooze="${_e(personId)}">Snooze</button>` : ''}
        ${active ? `<button type="button" class="cal-btn" data-followup-dismiss="${_e(personId)}">Dismiss</button>` : ''}
        ${!active ? `<button type="button" class="cal-btn" data-followup-restore="${_e(personId)}">Restore</button>` : ''}
      </div>
    </div>
  `;
}

export function renderFollowupsHtml({
  followups = [],
  counts = {},
  busy = false,
  error = '',
} = {}) {
  const activeCount = Number(counts.active ?? followups.length ?? 0);
  const rows = (followups || []).map(followupCardHtml).join('');
  return `
    <section class="logbook-followups-panel">
      <div class="logbook-section-head">
        <h5>Follow-up</h5>
        <span class="logbook-followup-count">${activeCount} active</span>
      </div>
      ${busy ? '<div class="logbook-empty">Loading follow-ups...</div>' : ''}
      ${error ? `<div class="logbook-ai-error">${_e(error)}</div>` : ''}
      ${!busy && !error && !rows ? '<div class="logbook-empty">No active follow-ups right now.</div>' : ''}
      ${rows ? `<div class="logbook-followup-list">${rows}</div>` : ''}
    </section>
  `;
}
