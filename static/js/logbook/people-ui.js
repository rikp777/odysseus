import { logbookIcon } from './icons.js';
import { escapeHtml as _e } from './utils.js';

function titleize(value) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
}

export function connectionTypeLabel(type) {
  const value = String(type || 'connection').trim().toLowerCase();
  const labels = {
    co_mentioned: 'Co-mentioned',
    family: 'Family',
    friend: 'Friend',
    work: 'Work',
    training: 'Training',
    conflict: 'Conflict',
    unknown: 'Connection',
  };
  return labels[value] || titleize(value);
}

export function factTypeLabel(type) {
  const value = String(type || 'fact').trim().toLowerCase();
  const labels = {
    workplace: 'Workplace',
    relationship: 'Relationship',
    role: 'Role',
    location: 'Location',
    preference: 'Preference',
    note: 'Note',
    unknown: 'Fact',
  };
  return labels[value] || titleize(value);
}

export function safePersonImage(src) {
  const value = String(src || '').trim();
  if (!value) return '';
  if (/^https?:\/\//i.test(value) || value.startsWith('/')) return value;
  if (/^data:image\/(?:png|jpe?g|gif|webp);base64,/i.test(value)) return value;
  return '';
}

export function connectionPersonChip(person, fallback, { personAttribute = 'data-open-person' } = {}) {
  const name = person?.display_name || fallback || 'Person';
  const attrs = person?.id ? ` type="button" ${personAttribute}="${_e(person.id)}"` : '';
  const tag = person?.id ? 'button' : 'span';
  return `<${tag} class="logbook-connection-person"${attrs}>${logbookIcon('person', 12)}<span>${_e(name)}</span></${tag}>`;
}

export function connectionEvidenceHtml(ev) {
  if (!ev?.snippet) return '';
  const date = ev.entry_date ? `<span class="logbook-evidence-date">${_e(ev.entry_date)}</span>` : '';
  return `<div class="logbook-evidence">${date}<span>${_e(ev.snippet)}</span></div>`;
}

export function connectionCardHtml(conn, {
  personAttribute = 'data-open-person',
  actionsHtml = '',
  wrapActions = true,
} = {}) {
  const status = conn.status === 'accepted' ? 'accepted' : 'suggested';
  const confidence = Math.max(0, Math.min(100, Number(conn.confidence || 0)));
  const ev = Array.isArray(conn.evidence) && conn.evidence.length ? conn.evidence[conn.evidence.length - 1] : null;
  const actions = typeof actionsHtml === 'function' ? actionsHtml(conn, status) : actionsHtml;
  const actionBlock = actions ? (
    wrapActions ? `<div class="logbook-connection-actions">${actions}</div>` : actions
  ) : '';
  return `
    <div class="logbook-connection ${status}">
      <div class="logbook-connection-head">
        <div class="logbook-connection-people">
          ${connectionPersonChip(conn.person_a, 'Person A', { personAttribute })}
          <span class="logbook-connection-plus">+</span>
          ${connectionPersonChip(conn.person_b, 'Person B', { personAttribute })}
        </div>
        <span class="logbook-connection-status ${status}">${status === 'accepted' ? 'Accepted' : 'Review'}</span>
      </div>
      <div class="logbook-connection-badges">
        <span class="logbook-connection-badge">${_e(connectionTypeLabel(conn.connection_type))}</span>
        <span class="logbook-connection-badge">${confidence}% confidence</span>
        ${conn.strength ? `<span class="logbook-connection-badge">strength ${_e(conn.strength)}</span>` : ''}
      </div>
      ${conn.description ? `<div class="logbook-connection-reason">${_e(conn.description)}</div>` : ''}
      ${connectionEvidenceHtml(ev)}
      ${actionBlock}
    </div>
  `;
}
