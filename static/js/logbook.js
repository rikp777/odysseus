/**
 * Daily Logbook module.
 */

import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { applyEdgeDock } from './modalSnap.js';
import {
  analyzeEntry,
  applyEntrySuggestions,
  assistLogbook,
  createLocation,
  getAIStatus,
  getEntry,
  getEntryRevision,
  listConnections,
  listEntryRevisions,
  listEntries,
  listLocations,
  listPeople,
  restoreEntryRevision,
  saveEntry,
  updateConnection,
} from './logbook/api.js';
import { MODAL_ID, MOODS, QUICK_DATA, SAVE_DELAY } from './logbook/constants.js';
import { iconBook as _iconBook, logbookIcon as _logbookIcon } from './logbook/icons.js';
import {
  cleanKey as _cleanKey,
  dateAdd as _dateAdd,
  dateLabel as _dateLabel,
  escapeHtml as _e,
  today as _today,
} from './logbook/utils.js';

const LOGBOOK_LINK_RE = /\[([^\]\n]{1,160})\]\((person:[A-Za-z0-9_-]{2,100}|place:[A-Za-z0-9_-]{2,100}|location:[A-Za-z0-9_-]{2,100}|data:[A-Za-z0-9_-]{2,80}|food:[A-Za-z0-9_-]{2,100}|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\)/g;
const LOGBOOK_PERSON_RE = /(^|[^\w.])@(?:\[([^\]\n]{1,80})\]|"([^"\n]{1,80})"|([A-Za-z0-9À-ÖØ-öø-ÿ][A-Za-z0-9À-ÖØ-öø-ÿ_-]*(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-z0-9À-ÖØ-öø-ÿ0-9_-]*|van|de|der|den|ten|ter|von|da|del|di|la|le|du)){0,3}))/g;
const LOGBOOK_LOCATION_RE = /(^|[^\w#])#(?:\[([^\]\n]{1,80})\]|"([^"\n]{1,80})"|([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-z0-9À-ÖØ-öø-ÿ_-]*(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-z0-9À-ÖØ-öø-ÿ0-9_-]*|van|de|der|den|ten|ter|von|da|del|di|la|le|du)){0,3}))/g;

let _open = false;
let _date = _today();
let _entry = null;
let _entries = [];
let _people = [];
let _locations = [];
let _connections = [];
let _saveTimer = null;
let _dirty = false;
let _saving = false;
let _saveStatus = 'Saved';
let _activeTab = 'write';
let _aiPreview = null;
let _aiBusy = false;
let _aiError = '';
let _aiStatus = { available: false, reason: 'Checking AI provider...' };
let _search = '';
let _filterPerson = '';
let _filterLocation = '';
let _filterMood = '';
let _filterDataKey = '';
let _windowRect = null;
let _peopleSearch = '';
let _locationSearch = '';
let _peopleSort = 'recent';
let _locationSort = 'recent';
let _editorMode = 'rich';
let _entitySignature = '';
let _historyOpen = false;
let _historyBusy = false;
let _historyError = '';
let _revisions = [];
let _revisionPreview = null;
let _revisionPreviewBusy = false;

function _setStatus(text) {
  _saveStatus = text;
  const el = document.getElementById('logbook-save-status');
  if (el) el.textContent = text;
}

function _markDirty() {
  _dirty = true;
  _setStatus('Unsaved');
  _refreshTokenEstimate();
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {
    _saveNow().catch(() => {});
  }, SAVE_DELAY);
}

function _entryPayload() {
  const datapoints = (_entry?.datapoints || []).map((dp, index) => ({
    key: _cleanKey(dp.key || dp.label),
    label: dp.label || '',
    value_text: dp.value_text || '',
    value_number: dp.value_number === '' || dp.value_number == null ? null : Number(dp.value_number),
    unit: dp.unit || '',
    value_json: dp.value_json ?? null,
    sort_order: index,
  }));
  return {
    title: _entry?.title || 'Daily log',
    content: _entry?.content || '',
    mood_label: _entry?.mood_label || null,
    mood_score: _entry?.mood_score ?? null,
    energy_score: _entry?.energy_score ?? null,
    stress_score: _entry?.stress_score ?? null,
    datapoints,
  };
}

async function _saveNow({ silent = false } = {}) {
  if (!_entry || _saving) return;
  _syncEntryFromEditor();
  if (_saveTimer) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
  }
  _saving = true;
  _setStatus('Saving...');
  try {
    const saved = await saveEntry(_date, _entryPayload());
    _entry = saved;
    _entitySignature = _entityListSignature(_entry.people || [], _entry.locations || []);
    _dirty = false;
    _setStatus('Saved');
    await Promise.all([_loadPeople(), _loadLocations(), _loadConnections(), _loadEntries()]);
    if (_historyOpen && _entry?.id) await _loadRevisions();
    _syncHistoryButtonState();
    _renderPeoplePanel();
    _renderLocationsPanel();
    _renderNavigator();
    _renderHistoryPanel();
    _refreshEditorContent({ preserveFocus: true });
    window.dispatchEvent(new CustomEvent('logbook-entries-refresh', { detail: { date: _date, entry: saved } }));
    if (!silent) uiModule?.showToast?.('Saved');
  } catch (err) {
    _setStatus('Save failed');
    if (!silent) uiModule?.showError?.(err.message || 'Save failed');
    throw err;
  } finally {
    _saving = false;
  }
}

function _normalizeEntryShape(entry) {
  const next = entry || {};
  if (!next.datapoints) next.datapoints = [];
  if (!next.people) next.people = [];
  if (!next.mentions) next.mentions = [];
  if (!next.locations) next.locations = [];
  if (!next.location_mentions) next.location_mentions = [];
  return next;
}

async function _loadEntry(date) {
  _entry = _normalizeEntryShape(await getEntry(date));
  _revisions = [];
  _revisionPreview = null;
  _historyError = '';
  if (_historyOpen && _entry?.id) await _loadRevisions();
  _entitySignature = _entityListSignature(_entry.people || [], _entry.locations || []);
  _dirty = false;
  _setStatus('Saved');
}

async function _loadRevisions() {
  if (!_entry?.id) {
    _revisions = [];
    return;
  }
  _historyBusy = true;
  _historyError = '';
  try {
    const data = await listEntryRevisions(_entry.id, 30);
    _revisions = data.revisions || [];
    if (_revisionPreview && !_revisions.some(revision => revision.id === _revisionPreview.id)) {
      _revisionPreview = null;
    }
  } catch (err) {
    _historyError = err?.message || 'History could not be loaded';
    _revisions = [];
  } finally {
    _historyBusy = false;
  }
}

function _syncHistoryButtonState() {
  const btn = document.getElementById('logbook-history-toggle');
  if (!btn) return;
  const disabled = !_entry?.id;
  btn.disabled = disabled;
  if (disabled) btn.setAttribute('title', 'Save this entry before history is available');
  else btn.removeAttribute('title');
}

async function _loadEntries() {
  const start = _dateAdd(_today(), -21);
  const end = _dateAdd(_today(), 7);
  const params = new URLSearchParams({ start, end });
  if (_search.trim()) params.set('q', _search.trim());
  if (_filterPerson) params.set('person_id', _filterPerson);
  if (_filterLocation) params.set('location_id', _filterLocation);
  if (_filterMood) params.set('mood', _filterMood);
  if (_filterDataKey.trim()) params.set('datapoint_key', _filterDataKey.trim());
  const data = await listEntries(params);
  _entries = data.entries || [];
}

async function _loadPeople() {
  const data = await listPeople();
  _people = data.people || [];
}

async function _loadLocations() {
  const data = await listLocations({ includeHidden: true });
  _locations = data.locations || [];
}

async function _loadConnections() {
  const data = await listConnections();
  _connections = data.connections || [];
}

async function _loadAIStatus() {
  try {
    _aiStatus = await getAIStatus();
  } catch (err) {
    _aiStatus = {
      available: false,
      reason: err?.message || 'AI status could not be checked',
    };
  }
}

async function _loadDate(date) {
  if (_dirty) {
    try { await _saveNow({ silent: true }); } catch (_) {}
  }
  _date = date;
  _aiPreview = null;
  _aiError = '';
  await Promise.all([_loadEntry(_date), _loadPeople(), _loadLocations(), _loadConnections(), _loadEntries(), _loadAIStatus()]);
  _render();
}

function _slugName(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/^(person|place|location|data|food):/i, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function _linkKind(target) {
  const value = String(target || '').toLowerCase();
  if (value.startsWith('place:') || value.startsWith('location:')) return 'location';
  if (value.startsWith('data:') || value.startsWith('food:')) return 'data';
  return 'person';
}

function _personForLink(target, label = '') {
  const targetSlug = _slugName(target);
  const labelSlug = _slugName(label);
  return (_people || []).find(person => {
    const slugs = [
      person.canonical_name,
      person.display_name,
      ...(person.aliases || []),
    ].map(_slugName).filter(Boolean);
    return slugs.includes(targetSlug) || Boolean(labelSlug && slugs.includes(labelSlug));
  }) || null;
}

function _locationForLink(target, label = '', { includeHidden = false } = {}) {
  const targetSlug = _slugName(target);
  const labelSlug = _slugName(label);
  return (_locations || []).find(location => {
    if (location.hidden && !includeHidden) return false;
    const slugs = [
      location.canonical_name,
      location.display_name,
      ...(location.aliases || []),
    ].map(_slugName).filter(Boolean);
    return slugs.includes(targetSlug) || Boolean(labelSlug && slugs.includes(labelSlug));
  }) || null;
}

function _displayNameFromSlug(value) {
  const particles = new Set(['van', 'de', 'der', 'den', 'ten', 'ter', 'von', 'da', 'del', 'di', 'la', 'le', 'du']);
  return _slugName(value)
    .split('_')
    .filter(Boolean)
    .map((part, index) => (index > 0 && particles.has(part)) ? part : part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function _entityKey(item) {
  return item?.id || _slugName(item?.canonical_name || item?.display_name || '');
}

function _addEntity(list, item) {
  const key = _entityKey(item);
  if (!key || list.some(existing => _entityKey(existing) === key)) return;
  list.push(item);
}

function _entityFromLabel(kind, label, target = '') {
  if (kind === 'location') {
    const existing = _locationForLink(target, label, { includeHidden: true });
    if (existing?.hidden) return null;
    if (existing) return existing;
  }
  const existing = kind === 'location' ? null : _personForLink(target, label);
  if (existing) return existing;
  const displayName = label || _displayNameFromSlug(target);
  return displayName ? { id: '', display_name: displayName, canonical_name: _slugName(target || label) } : null;
}

function _currentEntitiesFromContent(content) {
  const text = String(content || '');
  const people = [];
  const locations = [];
  LOGBOOK_LINK_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_LINK_RE)) {
    const kind = _linkKind(match[2]);
    if (kind === 'location') _addEntity(locations, _entityFromLabel('location', match[1], match[2]));
    else if (kind !== 'data') _addEntity(people, _entityFromLabel('person', match[1], match[2]));
  }
  LOGBOOK_PERSON_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_PERSON_RE)) {
    const label = (match[2] || match[3] || match[4] || '').replace(/\s+/g, ' ').trim();
    if (label) _addEntity(people, _entityFromLabel('person', label));
  }
  LOGBOOK_LOCATION_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_LOCATION_RE)) {
    const label = (match[2] || match[3] || match[4] || '').replace(/\s+/g, ' ').trim();
    if (label) _addEntity(locations, _entityFromLabel('location', label));
  }
  return { people, locations };
}

function _entityListSignature(people = [], locations = []) {
  const personKeys = people.map(_entityKey).filter(Boolean).sort().join(',');
  const locationKeys = locations.map(_entityKey).filter(Boolean).sort().join(',');
  return `${personKeys}|${locationKeys}`;
}

function _syncCurrentEntryEntitiesFromContent() {
  if (!_entry) return false;
  const { people, locations } = _currentEntitiesFromContent(_entry.content || '');
  const nextSignature = _entityListSignature(people, locations);
  const changed = nextSignature !== _entitySignature;
  _entry.people = people;
  _entry.locations = locations;
  _entry.people_count = people.length;
  _entry.location_count = locations.length;
  _entry.mention_count = people.length;
  _entry.location_mention_count = locations.length;
  _entitySignature = nextSignature;
  return changed;
}

function _refreshEntityPanelsFromContent() {
  if (!_syncCurrentEntryEntitiesFromContent()) return;
  _renderPeoplePanel();
  _renderLocationsPanel();
  _renderNavigator();
}

function _safePersonImage(src) {
  const value = String(src || '').trim();
  if (!value) return '';
  if (/^https?:\/\//i.test(value) || value.startsWith('/')) return value;
  if (/^data:image\/(?:png|jpe?g|gif|webp);base64,/i.test(value)) return value;
  return '';
}

function _personCardHtml(person, label, target) {
  const snapshot = person?.contact_snapshot || {};
  const image = _safePersonImage(snapshot.photo || snapshot.avatar || snapshot.image || snapshot.image_url || snapshot.picture);
  const name = person?.display_name || label || target || 'Person';
  const relation = person?.relationship_label || '';
  const notes = person?.notes || person?.llm_context || '';
  const emails = Array.isArray(snapshot.emails) ? snapshot.emails : (snapshot.email ? [snapshot.email] : []);
  const phones = Array.isArray(snapshot.phones) ? snapshot.phones : (snapshot.phone ? [snapshot.phone] : []);
  const contactBits = [
    snapshot.name,
    ...emails,
    ...phones,
  ].filter(Boolean);
  const initial = String(name).trim().slice(0, 1).toUpperCase() || '?';
  const connections = _personConnectionsPreviewHtml(person, { limit: 3 });
  return `
    <span class="logbook-person-card" role="tooltip">
      <span class="logbook-person-card-head">
        ${image ? `<img src="${_e(image)}" alt="">` : `<span class="logbook-person-initial logbook-card-icon" title="${_e(initial)}">${_logbookIcon('person', 16)}</span>`}
        <span><strong>${_e(name)}</strong>${relation ? `<em>${_e(relation)}</em>` : ''}</span>
      </span>
      ${notes ? `<span class="logbook-person-card-note">${_e(notes)}</span>` : ''}
      ${connections}
      ${contactBits.length ? `<span class="logbook-person-card-note">${_e(contactBits.slice(0, 3).join(' | '))}</span>` : ''}
      ${person?.id ? '<span class="logbook-person-card-link">Open person</span>' : '<span class="logbook-person-card-link">Apply or save to create this person</span>'}
    </span>
  `;
}

function _renderPersonLink(label, target) {
  const person = _personForLink(target, label);
  const attrs = person?.id ? ` data-open-person="${_e(person.id)}" role="button"` : ' role="text"';
  return `<span class="logbook-person-link" tabindex="0"${attrs}><span class="logbook-link-label">${_logbookIcon('person', 12)}<span>${_e(label)}</span></span>${_personCardHtml(person, label, target)}</span>`;
}

function _locationCardHtml(location, label, target) {
  const name = location?.display_name || label || target || 'Place';
  const kind = location?.location_type || '';
  const address = location?.address || '';
  const notes = location?.notes || location?.llm_context || '';
  const coords = location?.latitude != null && location?.longitude != null
    ? `${location.latitude}, ${location.longitude}`
    : '';
  return `
    <span class="logbook-person-card logbook-location-card" role="tooltip">
      <span class="logbook-person-card-head">
        <span class="logbook-person-initial logbook-card-icon">${_logbookIcon('location', 16)}</span>
        <span><strong>${_e(name)}</strong>${kind ? `<em>${_e(kind)}</em>` : ''}</span>
      </span>
      ${address ? `<span class="logbook-person-card-note">${_e(address)}</span>` : ''}
      ${coords ? `<span class="logbook-person-card-note">${_e(coords)}</span>` : ''}
      ${notes ? `<span class="logbook-person-card-note">${_e(notes)}</span>` : ''}
      ${location?.id ? '<span class="logbook-person-card-link">Open place</span>' : '<span class="logbook-person-card-link">Save to create this place</span>'}
    </span>
  `;
}

function _renderLocationLink(label, target) {
  const location = _locationForLink(target, label);
  const attrs = location?.id ? ` data-open-location="${_e(location.id)}" role="button"` : ' role="text"';
  return `<span class="logbook-person-link logbook-location-link" tabindex="0"${attrs}><span class="logbook-link-label">${_logbookIcon('location', 12)}<span>${_e(label)}</span></span>${_locationCardHtml(location, label, target)}</span>`;
}

function _dataCardHtml(label, target) {
  const rawKey = String(target || '').split(':', 2);
  const key = rawKey[0] === 'food' ? 'food' : _slugName(rawKey[1] || target || 'data');
  const display = key.replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
  return `
    <span class="logbook-person-card logbook-data-card" role="tooltip">
      <span class="logbook-person-card-head">
        <span class="logbook-person-initial logbook-card-icon">${_logbookIcon('food', 16)}</span>
        <span><strong>${_e(display)}</strong><em>Datapoint</em></span>
      </span>
      <span class="logbook-person-card-note">${_e(label)}</span>
      <span class="logbook-person-card-link">Saved as structured data</span>
    </span>
  `;
}

function _renderDataLink(label, target) {
  return `<span class="logbook-person-link logbook-data-link" tabindex="0" role="text"><span class="logbook-link-label">${_logbookIcon('food', 12)}<span>${_e(label)}</span></span>${_dataCardHtml(label, target)}</span>`;
}

function _editorTokenHtml(label, target) {
  const kind = _linkKind(target);
  const cls = kind === 'location'
    ? 'logbook-editor-token-place'
    : kind === 'data' ? 'logbook-editor-token-data' : 'logbook-editor-token-person';
  const iconKind = kind === 'location' ? 'location' : kind === 'data' ? 'food' : 'person';
  const card = kind === 'location'
    ? _locationCardHtml(_locationForLink(target, label), label, target)
    : kind === 'data' ? _dataCardHtml(label, target) : _personCardHtml(_personForLink(target, label), label, target);
  let openAttrs = ' role="text"';
  if (kind === 'location') {
    const location = _locationForLink(target, label);
    if (location?.id) {
      openAttrs = ` role="button" tabindex="0" data-open-location="${_e(location.id)}" aria-label="Open place ${_e(label)}"`;
    }
  } else if (kind !== 'data') {
    const person = _personForLink(target, label);
    if (person?.id) {
      openAttrs = ` role="button" tabindex="0" data-open-person="${_e(person.id)}" aria-label="Open person ${_e(label)}"`;
    }
  }
  return `<span class="logbook-editor-token ${cls}" contenteditable="false" data-logbook-token="1" data-target="${_e(target)}" data-label="${_e(label)}"${openAttrs}><span class="logbook-editor-token-icon">${_logbookIcon(iconKind, 12)}</span><span>${_e(label)}</span>${card}</span>`;
}

function _renderLogbookEditorText(content) {
  const text = String(content || '');
  let html = '';
  let last = 0;
  LOGBOOK_LINK_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_LINK_RE)) {
    html += _e(text.slice(last, match.index));
    html += _editorTokenHtml(match[1], match[2]);
    last = match.index + match[0].length;
  }
  html += _e(text.slice(last));
  return html;
}

function _renderLogbookText(content) {
  const text = String(content || '');
  let html = '';
  let last = 0;
  LOGBOOK_LINK_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_LINK_RE)) {
    html += _e(text.slice(last, match.index));
    const kind = _linkKind(match[2]);
    if (kind === 'location') html += _renderLocationLink(match[1], match[2]);
    else if (kind === 'data') html += _renderDataLink(match[1], match[2]);
    else html += _renderPersonLink(match[1], match[2]);
    last = match.index + match[0].length;
  }
  html += _e(text.slice(last));
  return html || '<span class="logbook-empty">No text yet.</span>';
}

function _blockNeedsNewline(el) {
  return el && /^(DIV|P|LI|H[1-6]|BLOCKQUOTE)$/i.test(el.nodeName || '');
}

function _serializeRichEditorNode(node, root) {
  if (!node) return '';
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue.replace(/\u00a0/g, ' ');
  if (node.nodeType !== Node.ELEMENT_NODE) return '';
  if (node.dataset?.logbookToken === '1') {
    const label = node.dataset.label || node.textContent.replace(/^[@#]/, '').trim();
    const target = node.dataset.target || '';
    return label && target ? `[${label}](${target})` : node.textContent || '';
  }
  if (node.nodeName === 'BR') return '\n';
  let out = '';
  node.childNodes.forEach(child => { out += _serializeRichEditorNode(child, root); });
  if (node !== root && _blockNeedsNewline(node) && out && !out.endsWith('\n')) out += '\n';
  return out;
}

function _richEditorToMarkdown(editor = document.getElementById('logbook-rich-content')) {
  if (!editor) return '';
  return _serializeRichEditorNode(editor, editor).replace(/\n{3,}/g, '\n\n').replace(/[ \t]+\n/g, '\n').trimEnd();
}

function _syncEntryFromEditor() {
  const raw = document.getElementById('logbook-content');
  const rich = document.getElementById('logbook-rich-content');
  if (!rich && !raw) return '';
  const value = _editorMode === 'raw' ? (raw?.value || '') : _richEditorToMarkdown(rich);
  if (_entry) _entry.content = value;
  _refreshTokenEstimate(value);
  return value;
}

function _estimateEntryTokens(content) {
  const text = String(content || '');
  if (!text.trim()) return 0;
  return Math.max(1, Math.round(text.length * 0.3));
}

function _formatTokenCount(count) {
  const value = Number(count || 0);
  return `${value.toLocaleString()} token${value === 1 ? '' : 's'}`;
}

function _refreshTokenEstimate(content = null) {
  const el = document.getElementById('logbook-token-count');
  if (!el) return;
  const text = content == null ? (_entry?.content || '') : content;
  el.textContent = _formatTokenCount(_estimateEntryTokens(text));
}

function _refreshEditorContent({ preserveFocus = false } = {}) {
  const raw = document.getElementById('logbook-content');
  const rich = document.getElementById('logbook-rich-content');
  const value = _entry?.content || '';
  if (raw && raw.value !== value) raw.value = value;
  if (rich && (!preserveFocus || document.activeElement !== rich)) {
    rich.innerHTML = _renderLogbookEditorText(value);
    _bindEntityLinkEvents(rich);
  }
}

function _entryStatus(entry) {
  if (!entry || !entry.exists) return 'empty';
  if (entry.people_count) return 'people';
  if (entry.location_count) return 'places';
  if (entry.mood_label) return 'mood';
  return 'entry';
}

function _scoreButtons(field, label) {
  const current = _entry?.[field] ?? '';
  const buttons = [1, 2, 3, 4, 5].map(n => (
    `<button type="button" class="logbook-score ${Number(current) === n ? 'active' : ''}" data-score-field="${field}" data-score="${n}">${n}</button>`
  )).join('');
  return `<div class="logbook-score-row"><span>${_e(label)}</span><div>${buttons}</div></div>`;
}

function _renderShell() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = MODAL_ID;
  modal.className = 'modal logbook-modal';
  document.body.appendChild(modal);
  Modals.register(MODAL_ID, {
    railBtnId: 'rail-logbook',
    sidebarBtnId: 'tool-logbook-btn',
    label: 'Logbook',
    icon: _iconBook(14),
    restoreFn: () => {
      _open = true;
      modal.classList.remove('hidden');
    },
    closeFn: closeLogbook,
  });
  return modal;
}

function _captureWindowRect(modal) {
  if (!modal || window.innerWidth <= 980) return;
  if (modal.classList.contains('modal-left-docked') || modal.classList.contains('modal-right-docked')) return;
  const content = modal.querySelector('.logbook-modal-content');
  if (!content) return;
  const rect = content.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  _windowRect = {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
}

function _restoreWindowRect(modal) {
  if (!modal || window.innerWidth <= 980) return;
  const content = modal.querySelector('.logbook-modal-content');
  if (!content) return;
  const dockSide = modal.classList.contains('modal-left-docked')
    ? 'left'
    : modal.classList.contains('modal-right-docked') ? 'right' : null;
  if (dockSide) {
    applyEdgeDock(modal, dockSide);
    return;
  }
  if (!_windowRect) return;
  const width = Math.min(_windowRect.width, window.innerWidth - 16);
  const height = Math.min(_windowRect.height, window.innerHeight - 16);
  const left = Math.max(8, Math.min(_windowRect.left, window.innerWidth - width - 8));
  const top = Math.max(8, Math.min(_windowRect.top, window.innerHeight - height - 8));
  content.style.position = 'fixed';
  content.style.left = `${left}px`;
  content.style.top = `${top}px`;
  content.style.width = `${width}px`;
  content.style.height = `${height}px`;
  content.style.maxHeight = `${height}px`;
  content.style.transform = 'none';
  content.style.margin = '0';
}

function _wireLogbookWindow(modal) {
  const content = modal?.querySelector('.logbook-modal-content');
  const header = modal?.querySelector('.logbook-modal-header');
  if (!modal || !content || !header) return;
  _restoreWindowRect(modal);
  makeWindowDraggable(modal, {
    content,
    header,
    skipSelector: 'button, input, select, textarea, label, [contenteditable="true"]',
    mobileSkip: 980,
    enableDock: true,
    onDragEnd: () => _captureWindowRect(modal),
  });
}

function _logbookTabLabel(tab) {
  return tab === 'ai' ? 'AI' : tab[0].toUpperCase() + tab.slice(1);
}

function _ensureLogbookContent(modal) {
  if (modal.querySelector('.logbook-modal-content')) return false;
  modal.innerHTML = `
    <div class="modal-content logbook-modal-content" role="dialog" aria-label="Daily Logbook">
      <div class="modal-header logbook-modal-header">
        <h4 class="logbook-title">${_iconBook(14)}<span>Logbook</span></h4>
        <div class="logbook-date-controls">
          <button type="button" class="cal-btn" id="logbook-prev-day">Prev</button>
          <input type="date" id="logbook-date-input">
          <button type="button" class="cal-btn" id="logbook-next-day">Next</button>
          <button type="button" class="cal-btn" id="logbook-today-btn">Today</button>
        </div>
        <span id="logbook-save-status" class="logbook-save-status"></span>
        <button type="button" class="cal-btn cal-btn-primary" id="logbook-manual-save">Save</button>
        <button type="button" class="close-btn" id="logbook-close" title="Close" aria-label="Close">&#x2716;</button>
      </div>
      <div class="logbook-mobile-tabs">
        ${['write', 'mood', 'data', 'people', 'places', 'ai'].map(tab => `<button type="button" class="logbook-tab" data-logbook-tab="${tab}">${_logbookTabLabel(tab)}</button>`).join('')}
      </div>
      <div class="modal-body logbook-body"></div>
    </div>
  `;
  Modals.injectMinimizeButton(modal, MODAL_ID);
  _wireLogbookWindow(modal);
  _bindChromeEvents(modal);
  return true;
}

function _bodyHtml() {
  return `
    <aside class="logbook-nav" data-mobile-section="write">
      ${_navigatorHtml()}
    </aside>
    <main class="logbook-editor" data-mobile-section="write">
      ${_editorHtml()}
    </main>
    <aside class="logbook-side">
      <section class="logbook-panel" data-mobile-section="ai">
        ${_aiHtml()}
      </section>
      <section class="logbook-panel" data-mobile-section="people">
        ${_peopleHtml()}
        ${_connectionsHtml()}
      </section>
      <section class="logbook-panel" data-mobile-section="places">
        ${_locationsHtml()}
      </section>
    </aside>
  `;
}

function _syncChromeState(modal = document.getElementById(MODAL_ID)) {
  if (!modal) return;
  const dateInput = modal.querySelector('#logbook-date-input');
  if (dateInput && dateInput.value !== _date) dateInput.value = _date;
  _setStatus(_saveStatus);
  modal.querySelectorAll('[data-logbook-tab]').forEach(btn => {
    const active = btn.dataset.logbookTab === _activeTab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const body = modal.querySelector('.logbook-body');
  if (body) body.dataset.activeTab = _activeTab;
}

function _refreshMoodControls() {
  document.querySelectorAll('[data-mood]').forEach(btn => {
    btn.classList.toggle('active', _entry?.mood_label === btn.dataset.mood);
  });
}

function _refreshScoreControls(field) {
  document.querySelectorAll(`[data-score-field="${field}"]`).forEach(btn => {
    btn.classList.toggle('active', Number(_entry?.[field]) === Number(btn.dataset.score));
  });
}

function _render() {
  const modal = _renderShell();
  _captureWindowRect(modal);
  _ensureLogbookContent(modal);
  const body = modal.querySelector('.logbook-body');
  body.innerHTML = _bodyHtml();
  _syncChromeState(modal);
  _bindBodyEvents();
  _renderMentionMenu();
}

function _navigatorHtml() {
  const rows = _entries.map(entry => {
    const meta = [
      entry.mood_label || '',
      entry.people_count ? `${entry.people_count} people` : '',
      entry.location_count ? `${entry.location_count} places` : '',
      entry.datapoint_count ? `${entry.datapoint_count} data` : '',
    ].filter(Boolean).join(' | ');
    return `
      <button type="button" class="logbook-day-row ${entry.entry_date === _date ? 'active' : ''}" data-date="${_e(entry.entry_date)}">
        <span class="logbook-day-main">
          <span class="logbook-day-date">${_e(_dateLabel(entry.entry_date))}</span>
          ${entry.snippet ? `<span class="logbook-day-snippet">${_e(entry.snippet)}</span>` : ''}
          ${meta ? `<span class="logbook-day-meta">${_e(meta)}</span>` : ''}
        </span>
        <span class="logbook-day-state" data-state="${_e(_entryStatus(entry))}">${_e(_entryStatus(entry))}</span>
      </button>
    `;
  }).join('') || '<div class="logbook-empty">No entries in this range.</div>';
  const personOptions = _people.map(p => `<option value="${_e(p.id)}" ${_filterPerson === p.id ? 'selected' : ''}>${_e(p.display_name)}</option>`).join('');
  const locationOptions = _locations.map(l => `<option value="${_e(l.id)}" ${_filterLocation === l.id ? 'selected' : ''}>${_e(l.display_name)}</option>`).join('');
  const moodOptions = MOODS.map(m => `<option value="${_e(m.value)}" ${_filterMood === m.value ? 'selected' : ''}>${_e(m.label)}</option>`).join('');
  const activeFilters = [
    _filterPerson ? 'person' : '',
    _filterLocation ? 'place' : '',
    _filterMood ? 'mood' : '',
    _filterDataKey.trim() ? 'data' : '',
  ].filter(Boolean);
  return `
    <div class="logbook-nav-actions">
      <button type="button" class="cal-btn" data-jump-date="${_e(_today())}">Today</button>
      <button type="button" class="cal-btn" data-jump-date="${_e(_dateAdd(_today(), -1))}">Yesterday</button>
      ${activeFilters.length ? '<button type="button" class="cal-btn" id="logbook-clear-filters">Clear</button>' : ''}
    </div>
    <input id="logbook-entry-search" class="memory-search-input" placeholder="Search" value="${_e(_search)}">
    <select id="logbook-person-filter" class="logbook-select">
      <option value="">Any person</option>
      ${personOptions}
    </select>
    <select id="logbook-location-filter" class="logbook-select">
      <option value="">Any place</option>
      ${locationOptions}
    </select>
    <select id="logbook-mood-filter" class="logbook-select">
      <option value="">Any mood</option>
      ${moodOptions}
    </select>
    <input id="logbook-data-filter" class="memory-search-input" placeholder="Data key" value="${_e(_filterDataKey)}">
    <div class="logbook-recent-title">Recent days</div>
    <div class="logbook-day-list">${rows}</div>
  `;
}

function _editorHtml() {
  const mood = _entry?.mood_label || '';
  const moodChips = MOODS.map(item => `
    <button type="button" class="logbook-chip ${mood === item.value ? 'active' : ''}" data-mood="${_e(item.value)}" data-mood-score="${item.score}">${_e(item.label)}</button>
  `).join('');
  const richActive = _editorMode !== 'raw';
  const historyDisabled = !_entry?.id ? ' disabled title="Save this entry before history is available"' : '';
  return `
    <div class="logbook-editor-head">
      <div>
        <div class="logbook-date-title">${_e(_dateLabel(_date))}</div>
        <div class="logbook-date-sub">
          <span>${_e(_date)}</span>
          <span id="logbook-token-count" class="logbook-token-count" title="Approximate tokens in this day's text">${_formatTokenCount(_estimateEntryTokens(_entry?.content || ''))}</span>
        </div>
      </div>
      <div class="logbook-editor-actions">
        <button type="button" class="cal-btn ${_historyOpen ? 'active' : ''}" id="logbook-history-toggle"${historyDisabled}>History</button>
        <div class="logbook-editor-toggle" role="group" aria-label="Editor mode">
          <button type="button" class="${richActive ? 'active' : ''}" aria-pressed="${richActive ? 'true' : 'false'}" data-logbook-editor-mode="rich">Editor</button>
          <button type="button" class="${!richActive ? 'active' : ''}" aria-pressed="${!richActive ? 'true' : 'false'}" data-logbook-editor-mode="raw">Raw</button>
        </div>
      </div>
    </div>
    ${_historyOpen ? _historyHtml() : ''}
    <div class="logbook-link-toolbar" role="toolbar" aria-label="Link selected text">
      <button type="button" data-logbook-link-selection="person" title="Link selected text as person">${_logbookIcon('person', 13)}<span>Person</span></button>
      <button type="button" data-logbook-link-selection="location" title="Link selected text as place">${_logbookIcon('location', 13)}<span>Place</span></button>
      <button type="button" data-logbook-link-selection="food" title="Link selected text as food">${_logbookIcon('food', 13)}<span>Food</span></button>
      <button type="button" data-logbook-unlink-selection title="Remove link from selected token or markdown link">${_logbookIcon('unlink', 13)}<span>Unlink</span></button>
    </div>
    <section class="logbook-write-section" data-mobile-section="write">
      <div id="logbook-rich-content" class="logbook-rich-content ${richActive ? '' : 'hidden'}" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Logbook editor" data-placeholder="Write messy notes. Add people and places from the panels, or switch to Raw for markdown.">${_renderLogbookEditorText(_entry?.content || '')}</div>
      <textarea id="logbook-content" class="logbook-content ${richActive ? 'hidden' : ''}" placeholder="Write messy notes. Example: tired, talked with [Jan](person:jan), rode through [Meerstad](place:meerstad), ate [breakfast](data:food).">${_e(_entry?.content || '')}</textarea>
      <div id="logbook-mention-menu" class="logbook-mention-menu hidden"></div>
    </section>
    <section class="logbook-mood-section" data-mobile-section="mood">
      <h5>Mood</h5>
      <div class="logbook-chip-row">${moodChips}</div>
      ${_scoreButtons('energy_score', 'Energy')}
      ${_scoreButtons('stress_score', 'Stress')}
    </section>
    <section class="logbook-data-section" data-mobile-section="data">
      <div class="logbook-section-head">
        <h5>Data</h5>
        <button type="button" class="cal-btn" id="logbook-add-datapoint">Add</button>
      </div>
      <div class="logbook-quick-row">
        ${QUICK_DATA.map(([key, label]) => `<button type="button" class="logbook-chip" data-quick-data="${_e(key)}" data-quick-label="${_e(label)}">${_e(label)}</button>`).join('')}
      </div>
      <div id="logbook-datapoints" class="logbook-datapoints">${_datapointsHtml()}</div>
    </section>
  `;
}

function _formatRevisionTime(value) {
  if (!value) return '';
  try {
    return new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  } catch (_) {
    return value;
  }
}

function _revisionSourceLabel(source) {
  if (source === 'restore') return 'Before restore';
  if (source === 'ai_apply') return 'Before AI apply';
  return 'Saved version';
}

function _historyHtml() {
  if (!_entry?.id) {
    return '<section id="logbook-history-panel" class="logbook-history-panel"><div class="logbook-empty">Save this day before history is available.</div></section>';
  }
  const rows = _revisions.map(revision => `
    <div class="logbook-history-row ${_revisionPreview?.id === revision.id ? 'active' : ''}">
      <div class="logbook-history-main">
        <div class="logbook-history-title">
          <strong>${_e(_formatRevisionTime(revision.created_at))}</strong>
          <span>${_e(_revisionSourceLabel(revision.source))}</span>
        </div>
        ${revision.snippet ? `<div class="logbook-history-snippet">${_e(revision.snippet)}</div>` : ''}
        <div class="logbook-history-meta">
          ${revision.mood_label ? `<span>${_e(revision.mood_label)}</span>` : ''}
          ${revision.datapoint_count ? `<span>${revision.datapoint_count} data</span>` : ''}
        </div>
      </div>
      <button type="button" class="cal-btn" data-preview-revision="${_e(revision.id)}">${_revisionPreview?.id === revision.id ? 'Selected' : 'Preview'}</button>
    </div>
  `).join('');
  const preview = _revisionPreview ? `
    <div class="logbook-history-preview">
      <div class="logbook-section-head">
        <h5>Preview</h5>
        <button type="button" class="cal-btn" id="logbook-close-history-preview">Close</button>
      </div>
      <div class="logbook-history-preview-meta">
        <span>${_e(_formatRevisionTime(_revisionPreview.created_at))}</span>
        <span>${_e(_revisionSourceLabel(_revisionPreview.source))}</span>
        ${_revisionPreview.mood_label ? `<span>${_e(_revisionPreview.mood_label)}</span>` : ''}
        ${_revisionPreview.datapoint_count ? `<span>${_revisionPreview.datapoint_count} data</span>` : ''}
      </div>
      <div class="logbook-rendered-text logbook-history-preview-content">${_renderLogbookText(_revisionPreview.content || '')}</div>
      <div class="logbook-preview-actions">
        <button type="button" class="cal-btn cal-btn-primary" data-restore-revision="${_e(_revisionPreview.id)}">Restore this version</button>
      </div>
    </div>
  ` : '';
  return `
    <section id="logbook-history-panel" class="logbook-history-panel">
      <div class="logbook-section-head">
        <h5>History</h5>
        <button type="button" class="cal-btn" id="logbook-refresh-history"${_historyBusy ? ' disabled' : ''}>Refresh</button>
      </div>
      ${_historyBusy ? '<div class="logbook-empty">Loading history...</div>' : ''}
      ${_revisionPreviewBusy ? '<div class="logbook-empty">Loading preview...</div>' : ''}
      ${_historyError ? `<div class="logbook-ai-error">${_e(_historyError)}</div>` : ''}
      ${preview}
      ${rows || (!_historyBusy ? '<div class="logbook-empty">No saved versions yet.</div>' : '')}
    </section>
  `;
}

function _datapointsHtml() {
  const points = _entry?.datapoints || [];
  if (!points.length) return '<div class="logbook-empty">No datapoints.</div>';
  return points.map((dp, index) => `
    <div class="logbook-datapoint" data-datapoint-index="${index}">
      <input class="logbook-dp-label" value="${_e(dp.label || dp.key || '')}" placeholder="Label">
      <input class="logbook-dp-value" value="${_e(dp.value_text || '')}" placeholder="Value">
      <input class="logbook-dp-number" type="number" step="any" value="${dp.value_number ?? ''}" placeholder="#">
      <input class="logbook-dp-unit" value="${_e(dp.unit || '')}" placeholder="Unit">
      <button type="button" class="logbook-icon-btn" data-remove-datapoint="${index}" aria-label="Delete">x</button>
    </div>
  `).join('');
}

function _personSuggestionMeta(person) {
  const bits = [];
  if (person.relationship_label) bits.push(_connectionTypeLabel(person.relationship_label));
  if (Array.isArray(person.facts)) {
    person.facts.forEach(fact => {
      const label = fact?.label || _connectionTypeLabel(fact?.fact_type || 'fact');
      const value = fact?.value_text || '';
      if (value) bits.push(`${label}: ${value}`);
    });
  }
  if (person.llm_context) bits.push(person.llm_context);
  if (person.notes) bits.push(person.notes);
  if (person.reason) bits.push(person.reason);
  return bits.filter(Boolean).join(' | ') || 'Suggested from entry';
}

function _personSuggestionNames(person) {
  return [
    person?.display_name,
    person?.surface_text,
    ...(person?.aliases || []),
  ].map(name => _slugName(name)).filter(Boolean);
}

function _personSuggestionKnownPerson(person) {
  const names = new Set(_personSuggestionNames(person));
  if (!names.size) return null;
  return _people.find(known => _personSuggestionNames(known).some(name => names.has(name))) || null;
}

function _personSuggestionHasFacts(person) {
  return Array.isArray(person?.facts) && person.facts.some(fact => fact?.value_text);
}

function _personSuggestionActionLabel(person) {
  const known = _personSuggestionKnownPerson(person);
  if (known && _personSuggestionHasFacts(person)) return 'Save facts';
  if (known) return 'Link';
  return 'Add';
}

function _personFactsPreviewHtml(person, { limit = 2 } = {}) {
  const facts = Array.isArray(person?.facts)
    ? person.facts.filter(fact => fact && fact.value_text)
    : [];
  if (!facts.length) return '';
  const shown = facts.slice(0, limit);
  const chips = shown.map(fact => {
    const label = fact.label || _connectionTypeLabel(fact.fact_type || 'fact');
    const date = fact.last_seen_date || fact.source_entry_date || '';
    const title = [label, fact.value_text, date ? `last seen ${date}` : ''].filter(Boolean).join(' | ');
    return `<span class="logbook-person-fact-chip" title="${_e(title)}"><strong>${_e(label)}</strong><span>${_e(fact.value_text)}</span></span>`;
  }).join('');
  const extra = Math.max(0, facts.length - shown.length);
  return `<span class="logbook-person-facts-preview">${chips}${extra ? `<span class="logbook-person-fact-more">+${extra}</span>` : ''}</span>`;
}

function _peopleHtml() {
  const todayPeople = _entry?.people || [];
  const today = todayPeople.length
    ? todayPeople.map(p => `<span class="logbook-person-chip">${_logbookIcon('person', 12)}${_e(p.display_name)}</span>`).join('')
    : '<div class="logbook-empty">No people mentioned today.</div>';
  const suggestions = (_aiPreview?.people_suggestions || []).map((p, index) => `
    <div class="logbook-suggestion-row">
      <strong>${_e(p.display_name || p.surface_text || 'Person')}</strong>
      <span>${_e(_personSuggestionMeta(p))}</span>
      <button type="button" class="cal-btn" data-add-ai-person="${index}">${_e(_personSuggestionActionLabel(p))}</button>
    </div>
  `).join('');
  return `
    <div class="logbook-section-head"><h5>People</h5></div>
    <div class="logbook-chip-wrap">${today}</div>
    ${suggestions ? `<div class="logbook-subtitle">Suggested people</div>${suggestions}` : ''}
    <div class="logbook-directory-tools">
      <input id="logbook-people-search" class="memory-search-input" placeholder="Find people" value="${_e(_peopleSearch)}">
      <select id="logbook-people-sort" class="logbook-select">
        <option value="recent" ${_peopleSort === 'recent' ? 'selected' : ''}>Recent</option>
        <option value="count" ${_peopleSort === 'count' ? 'selected' : ''}>Most used</option>
        <option value="name" ${_peopleSort === 'name' ? 'selected' : ''}>Name</option>
      </select>
    </div>
    <div class="logbook-subtitle">All people</div>
    <div id="logbook-people-list" class="logbook-directory-list">${_peopleRowsHtml()}</div>
  `;
}

function _peopleRowsHtml() {
  const people = _visiblePeople();
  return people.map(p => {
    const aliases = (p.aliases || []).slice(0, 3).join(', ');
    const meta = _directoryMeta(p, aliases);
    const active = _filterPerson === p.id ? ' active' : '';
    const connections = _personConnectionsPreviewHtml(p, { limit: 2, compact: true });
    const facts = _personFactsPreviewHtml(p, { limit: 2 });
    return `
      <div class="logbook-directory-row${active}">
        <button type="button" class="logbook-directory-main" data-filter-person="${_e(p.id)}">
          <strong>${_logbookIcon('person', 12)}${_e(p.display_name)}</strong>
          <span>${_e(meta)}</span>
          ${facts}
          ${connections}
        </button>
        <button type="button" class="logbook-icon-btn" data-insert-person="${_e(p.display_name)}" aria-label="Insert">+</button>
      </div>
    `;
  }).join('') || '<div class="logbook-empty">No known people yet.</div>';
}

function _locationsHtml() {
  const todayLocations = _entry?.locations || [];
  const today = todayLocations.length
    ? todayLocations.map(l => `<span class="logbook-person-chip">${_logbookIcon('location', 12)}${_e(l.display_name)}</span>`).join('')
    : '<div class="logbook-empty">No places mentioned today.</div>';
  const suggestions = (_aiPreview?.location_suggestions || []).map((loc, index) => `
    <div class="logbook-suggestion-row">
      <strong>${_e(loc.display_name || loc.surface_text || 'Place')}</strong>
      <span>${_e(loc.reason || 'Suggested from entry')}</span>
      <button type="button" class="cal-btn" data-add-ai-location="${index}">Add</button>
    </div>
  `).join('');
  return `
    <div class="logbook-section-head"><h5>Places</h5></div>
    <div class="logbook-chip-wrap">${today}</div>
    ${suggestions ? `<div class="logbook-subtitle">Suggested places</div>${suggestions}` : ''}
    <div class="logbook-directory-tools">
      <input id="logbook-location-new" class="memory-search-input" placeholder="New place">
      <button type="button" class="cal-btn" id="logbook-create-location">Add</button>
    </div>
    <div class="logbook-directory-tools">
      <input id="logbook-location-search" class="memory-search-input" placeholder="Find places" value="${_e(_locationSearch)}">
      <select id="logbook-location-sort" class="logbook-select">
        <option value="recent" ${_locationSort === 'recent' ? 'selected' : ''}>Recent</option>
        <option value="count" ${_locationSort === 'count' ? 'selected' : ''}>Most used</option>
        <option value="name" ${_locationSort === 'name' ? 'selected' : ''}>Name</option>
      </select>
    </div>
    <div class="logbook-subtitle">All places</div>
    <div id="logbook-location-list" class="logbook-directory-list">${_locationRowsHtml()}</div>
  `;
}

function _locationRowsHtml() {
  const locations = _visibleLocations();
  return locations.map(loc => {
    const aliases = (loc.aliases || []).slice(0, 3).join(', ');
    const meta = _directoryMeta(loc, aliases);
    const active = _filterLocation === loc.id ? ' active' : '';
    return `
      <div class="logbook-directory-row${active}">
        <button type="button" class="logbook-directory-main" data-filter-location="${_e(loc.id)}">
          <strong>${_logbookIcon('location', 12)}${_e(loc.display_name)}</strong>
          <span>${_e(meta)}</span>
        </button>
        <button type="button" class="logbook-icon-btn" data-insert-location="${_e(loc.display_name)}" aria-label="Insert">+</button>
      </div>
    `;
  }).join('') || '<div class="logbook-empty">No places yet.</div>';
}

function _directoryMeta(item, aliases = '') {
  const count = Number(item.mention_count || 0);
  const bits = [];
  bits.push(`${count} ${count === 1 ? 'entry' : 'entries'}`);
  if (item.last_mentioned) bits.push(`last ${item.last_mentioned}`);
  if (aliases) bits.push(aliases);
  return bits.join(' | ');
}

function _visiblePeople() {
  const term = _peopleSearch.trim().toLowerCase();
  const list = _people.filter(p => {
    if (!term) return true;
    const factBits = Array.isArray(p.facts)
      ? p.facts.flatMap(fact => [fact?.label, fact?.fact_type, fact?.value_text])
      : [];
    const names = [
      p.display_name,
      ...(p.aliases || []),
      p.relationship_label,
      p.notes,
      p.llm_context,
      ...factBits,
    ].map(x => String(x || '').toLowerCase());
    return names.some(name => name.includes(term));
  });
  list.sort((a, b) => _directorySort(a, b, _peopleSort));
  return list;
}

function _visibleLocations() {
  const term = _locationSearch.trim().toLowerCase();
  const list = _locations.filter(loc => {
    if (loc.hidden) return false;
    if (!term) return true;
    const names = [loc.display_name, ...(loc.aliases || [])].map(x => String(x || '').toLowerCase());
    return names.some(name => name.includes(term));
  });
  list.sort((a, b) => _directorySort(a, b, _locationSort));
  return list;
}

function _directorySort(a, b, sort) {
  if (sort === 'name') return String(a.display_name || '').localeCompare(String(b.display_name || ''));
  if (sort === 'count') return Number(b.mention_count || 0) - Number(a.mention_count || 0)
    || String(a.display_name || '').localeCompare(String(b.display_name || ''));
  return String(b.last_mentioned || '').localeCompare(String(a.last_mentioned || ''))
    || Number(b.mention_count || 0) - Number(a.mention_count || 0)
    || String(a.display_name || '').localeCompare(String(b.display_name || ''));
}

function _personConnectionSummaries(person) {
  return Array.isArray(person?.connections_summary)
    ? person.connections_summary.filter(item => item && item.status !== 'hidden')
    : [];
}

function _connectionOtherName(summary) {
  return summary?.other_person?.display_name || 'Person';
}

function _personConnectionsPreviewHtml(person, { limit = 3, compact = false } = {}) {
  const summaries = _personConnectionSummaries(person).slice(0, limit);
  if (!summaries.length) return '';
  const rows = summaries.map(summary => {
    const status = summary.status === 'accepted' ? 'accepted' : 'suggested';
    const label = compact
      ? _connectionOtherName(summary)
      : `${_connectionOtherName(summary)} - ${_connectionTypeLabel(summary.connection_type)}`;
    return `<span class="logbook-person-connection-chip ${status}">${_logbookIcon('person', 11)}${_e(label)}</span>`;
  }).join('');
  const extra = Math.max(0, _personConnectionSummaries(person).length - summaries.length);
  return `<span class="logbook-person-connections ${compact ? 'compact' : ''}">${rows}${extra ? `<span class="logbook-person-connection-more">+${extra}</span>` : ''}</span>`;
}

function _connectionTypeLabel(type) {
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
  return labels[value] || value.replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
}

function _connectionPersonChip(person, fallback) {
  const name = person?.display_name || fallback || 'Person';
  const attrs = person?.id ? ` data-open-person="${_e(person.id)}" type="button"` : '';
  const tag = person?.id ? 'button' : 'span';
  return `<${tag} class="logbook-connection-person"${attrs}>${_logbookIcon('person', 12)}<span>${_e(name)}</span></${tag}>`;
}

function _connectionEvidenceHtml(ev) {
  if (!ev?.snippet) return '';
  const date = ev.entry_date ? `<span class="logbook-evidence-date">${_e(ev.entry_date)}</span>` : '';
  return `<div class="logbook-evidence">${date}<span>${_e(ev.snippet)}</span></div>`;
}

function _connectionCardHtml(conn) {
  const status = conn.status === 'accepted' ? 'accepted' : 'suggested';
  const confidence = Math.max(0, Math.min(100, Number(conn.confidence || 0)));
  const ev = Array.isArray(conn.evidence) && conn.evidence.length ? conn.evidence[conn.evidence.length - 1] : null;
  const actions = status === 'suggested'
    ? `<div class="logbook-connection-actions"><button type="button" class="cal-btn cal-btn-primary" data-accept-connection="${_e(conn.id)}">Accept</button><button type="button" class="cal-btn" data-hide-connection="${_e(conn.id)}">Hide</button></div>`
    : `<span class="logbook-accepted">Accepted</span>`;
  return `
    <div class="logbook-connection ${status}">
      <div class="logbook-connection-head">
        <div class="logbook-connection-people">
          ${_connectionPersonChip(conn.person_a, 'Person A')}
          <span class="logbook-connection-plus">+</span>
          ${_connectionPersonChip(conn.person_b, 'Person B')}
        </div>
        <span class="logbook-connection-status ${status}">${status === 'accepted' ? 'Accepted' : 'Review'}</span>
      </div>
      <div class="logbook-connection-badges">
        <span class="logbook-connection-badge">${_e(_connectionTypeLabel(conn.connection_type))}</span>
        <span class="logbook-connection-badge">${confidence}% confidence</span>
        ${conn.strength ? `<span class="logbook-connection-badge">strength ${_e(conn.strength)}</span>` : ''}
      </div>
      ${conn.description ? `<div class="logbook-connection-reason">${_e(conn.description)}</div>` : ''}
      ${_connectionEvidenceHtml(ev)}
      ${actions}
    </div>
  `;
}

function _connectionsHtml() {
  const visible = _connections.filter(c => c.status !== 'hidden');
  const rows = visible.map(_connectionCardHtml).join('');
  return `
    <div class="logbook-section-head"><h5>Connections</h5></div>
    <div id="logbook-connections">${rows || '<div class="logbook-empty">No connection suggestions yet.</div>'}</div>
  `;
}

function _aiHtml() {
  const aiAvailable = _aiStatus?.available === true;
  const disabled = aiAvailable ? '' : ' disabled aria-disabled="true"';
  const disabledTitle = aiAvailable ? '' : ` title="${_e(_aiStatus?.reason || 'No LLM provider configured')}"`;
  const extractFactsTitle = aiAvailable
    ? ' title="Extract person facts from this saved entry"'
    : disabledTitle;
  const preview = _aiPreview
    ? _aiPreviewHtml()
    : aiAvailable
      ? '<div class="logbook-empty">AI previews appear here.</div>'
      : '<div class="logbook-empty">Manual writing still works. Configure a default or utility LLM provider to enable AI help.</div>';
  return `
    <div class="logbook-section-head"><h5>AI help</h5></div>
    ${aiAvailable ? `<div class="logbook-ai-status">Using AI model${_aiStatus.model ? `: ${_e(_aiStatus.model)}` : ''}</div>` : `<div class="logbook-ai-disabled">AI help is off: ${_e(_aiStatus?.reason || 'No LLM provider configured')}.</div>`}
    <div class="logbook-ai-buttons">
      <button type="button" class="cal-btn cal-btn-primary" data-ai-mode="structure_day"${disabled}${disabledTitle}>Help me write today</button>
      <button type="button" class="cal-btn" data-ai-mode="clean_spelling"${disabled}${disabledTitle}>Clean spelling</button>
      <button type="button" class="cal-btn" data-ai-mode="ask_questions"${disabled}${disabledTitle}>Ask 3 questions</button>
      <button type="button" class="cal-btn" data-ai-mode="extract_people"${disabled}${disabledTitle}>Extract people</button>
      <button type="button" class="cal-btn" data-ai-mode="extract_locations"${disabled}${disabledTitle}>Extract places</button>
      <button type="button" class="cal-btn" data-ai-mode="extract_all"${disabled}${disabledTitle}>Detect text</button>
      <button type="button" class="cal-btn" data-ai-mode="summarize"${disabled}${disabledTitle}>Summarize</button>
      <button type="button" class="cal-btn" data-ai-mode="reflect"${disabled}${disabledTitle}>Reflect</button>
      <button type="button" class="cal-btn" id="logbook-extract-facts"${disabled}${extractFactsTitle}>Extract facts</button>
    </div>
    ${_aiBusy ? '<div class="logbook-ai-status">Thinking...</div>' : ''}
    ${_aiError ? `<div class="logbook-ai-error">${_e(_aiError)}</div>` : ''}
    <div id="logbook-ai-preview" class="logbook-ai-preview">${preview}</div>
  `;
}

function _aiPreviewHtml() {
  const p = _aiPreview || {};
  const warning = p.warning ? `<div class="logbook-ai-warning">${_e(p.warning)}</div>` : '';
  const questions = (p.questions || []).map(q => `<li>${_e(q)}</li>`).join('');
  const data = (p.datapoint_suggestions || []).map(d => `
    <div class="logbook-suggestion-row">
      <strong>${_e(d.label || d.key || 'Data')}</strong>
      <span>${_e(d.value_text || d.value_number || '')}${d.unit ? ` ${_e(d.unit)}` : ''}</span>
    </div>
  `).join('');
  const people = (p.people_suggestions || []).map((person, index) => `
    <div class="logbook-suggestion-row">
      <strong>${_e(person.display_name || person.surface_text || 'Person')}</strong>
      <span>${_e(_personSuggestionMeta(person))}</span>
      <button type="button" class="cal-btn" data-add-ai-person="${index}">${_e(_personSuggestionActionLabel(person))}</button>
    </div>
  `).join('');
  const locations = (p.location_suggestions || []).map((loc, index) => `
    <div class="logbook-suggestion-row">
      <strong>${_e(loc.display_name || loc.surface_text || 'Place')}</strong>
      <span>${_e(loc.reason || 'Suggested from entry')}</span>
      <button type="button" class="cal-btn" data-add-ai-location="${index}">Add</button>
    </div>
  `).join('');
  const connections = (p.connection_suggestions || []).map(c => `
    <div class="logbook-suggestion-row">
      <strong>${_e(c.person_a || 'Person')} + ${_e(c.person_b || 'Person')}</strong>
      <span>${_e(c.description || c.connection_type || 'Possible connection')}</span>
    </div>
  `).join('');
  return `
    ${warning}
    ${p.preview_content ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Preview</div><div class="logbook-rendered-text">${_renderLogbookText(p.preview_content)}</div></div>` : ''}
    ${p.summary ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Summary</div><p>${_e(p.summary)}</p></div>` : ''}
    ${p.reflection ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Reflection</div><p>${_e(p.reflection)}</p></div>` : ''}
    ${questions ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Questions</div><ul>${questions}</ul></div>` : ''}
    ${p.mood_suggestion ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Mood</div><p>${_e(p.mood_suggestion.label || '')} ${p.mood_suggestion.score ? `(${_e(p.mood_suggestion.score)})` : ''}</p><button type="button" class="cal-btn" id="logbook-apply-ai-mood">Use mood</button></div>` : ''}
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

async function _toggleHistory() {
  _syncEntryFromEditor();
  _historyOpen = !_historyOpen;
  if (_historyOpen) await _loadRevisions();
  _render();
}

async function _refreshHistory() {
  await _loadRevisions();
  _renderHistoryPanel();
}

async function _previewRevision(revisionId) {
  if (!_entry?.id || !revisionId) return;
  _revisionPreviewBusy = true;
  _historyError = '';
  _renderHistoryPanel();
  try {
    _revisionPreview = await getEntryRevision(_entry.id, revisionId);
  } catch (err) {
    _historyError = err?.message || 'Revision preview could not be loaded';
    _revisionPreview = null;
    throw err;
  } finally {
    _revisionPreviewBusy = false;
    _renderHistoryPanel();
  }
}

function _clearRevisionPreview() {
  _revisionPreview = null;
  _renderHistoryPanel();
}

async function _restoreRevision(revisionId) {
  if (!_entry?.id || !revisionId) return;
  if (!window.confirm('Restore this saved version? Current entry will be saved to history first.')) return;
  if (_dirty) await _saveNow({ silent: true });
  _historyBusy = true;
  _historyError = '';
  _renderHistoryPanel();
  try {
    const data = await restoreEntryRevision(_entry.id, revisionId);
    _entry = _normalizeEntryShape(data.entry);
    _date = _entry.entry_date || _date;
    _entitySignature = _entityListSignature(_entry.people || [], _entry.locations || []);
    _dirty = false;
    _setStatus('Saved');
    await Promise.all([_loadPeople(), _loadLocations(), _loadConnections(), _loadEntries()]);
    if (_historyOpen && _entry?.id) await _loadRevisions();
    _historyBusy = false;
    _revisionPreview = null;
    _render();
    uiModule?.showToast?.('Restored version');
  } catch (err) {
    _historyBusy = false;
    _historyError = err?.message || 'Restore failed';
    _renderHistoryPanel();
    throw err;
  }
}

function _bindHistoryEvents() {
  document.getElementById('logbook-history-toggle')?.addEventListener('click', () => _toggleHistory().catch(_showError));
  document.getElementById('logbook-refresh-history')?.addEventListener('click', () => _refreshHistory().catch(_showError));
  document.getElementById('logbook-close-history-preview')?.addEventListener('click', _clearRevisionPreview);
  document.querySelectorAll('[data-preview-revision]').forEach(btn => {
    btn.addEventListener('click', () => _previewRevision(btn.dataset.previewRevision).catch(_showError));
  });
  document.querySelectorAll('[data-restore-revision]').forEach(btn => {
    btn.addEventListener('click', () => _restoreRevision(btn.dataset.restoreRevision).catch(_showError));
  });
}

function _bindChromeEvents(root = document) {
  root.querySelector('#logbook-close')?.addEventListener('click', closeLogbook);
  root.querySelector('#logbook-prev-day')?.addEventListener('click', () => _loadDate(_dateAdd(_date, -1)).catch(_showError));
  root.querySelector('#logbook-next-day')?.addEventListener('click', () => _loadDate(_dateAdd(_date, 1)).catch(_showError));
  root.querySelector('#logbook-today-btn')?.addEventListener('click', () => _loadDate(_today()).catch(_showError));
  root.querySelector('#logbook-date-input')?.addEventListener('change', e => _loadDate(e.target.value).catch(_showError));
  root.querySelector('#logbook-manual-save')?.addEventListener('click', () => _saveNow().catch(_showError));
  root.querySelectorAll('[data-logbook-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      _syncEntryFromEditor();
      _activeTab = btn.dataset.logbookTab || 'write';
      _syncChromeState(document.getElementById(MODAL_ID));
    });
  });
}

function _bindBodyEvents() {
  _bindHistoryEvents();

  document.querySelectorAll('[data-logbook-editor-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      _syncEntryFromEditor();
      _editorMode = btn.dataset.logbookEditorMode === 'raw' ? 'raw' : 'rich';
      _hideMentionMenu();
      _render();
      const next = document.getElementById(_editorMode === 'raw' ? 'logbook-content' : 'logbook-rich-content');
      next?.focus();
    });
  });

  document.querySelectorAll('[data-logbook-link-selection]').forEach(btn => {
    btn.addEventListener('mousedown', event => event.preventDefault());
    btn.addEventListener('click', () => _linkSelectedText(btn.dataset.logbookLinkSelection || 'person'));
  });
  document.querySelectorAll('[data-logbook-unlink-selection]').forEach(btn => {
    btn.addEventListener('mousedown', event => event.preventDefault());
    btn.addEventListener('click', _unlinkSelectedText);
  });

  document.querySelectorAll('[data-jump-date]').forEach(btn => {
    btn.addEventListener('click', () => _loadDate(btn.dataset.jumpDate).catch(_showError));
  });
  document.querySelectorAll('[data-date]').forEach(btn => {
    btn.addEventListener('click', () => _loadDate(btn.dataset.date).catch(_showError));
  });
  document.getElementById('logbook-clear-filters')?.addEventListener('click', () => {
    _filterPerson = '';
    _filterLocation = '';
    _filterMood = '';
    _filterDataKey = '';
    _loadEntries().then(_renderNavigator).catch(_showError);
  });

  const content = document.getElementById('logbook-content');
  content?.addEventListener('input', () => {
    _entry.content = content.value;
    _refreshTokenEstimate(content.value);
    _refreshEntityPanelsFromContent();
    _markDirty();
    _renderMentionMenu();
  });
  content?.addEventListener('blur', () => {
    _entry.content = content.value;
    setTimeout(_hideMentionMenu, 180);
  });
  content?.addEventListener('keydown', e => {
    if (e.key === 'Escape') _hideMentionMenu();
  });
  content?.addEventListener('click', _renderMentionMenu);

  const rich = document.getElementById('logbook-rich-content');
  rich?.addEventListener('input', () => {
    _syncEntryFromEditor();
    _refreshEntityPanelsFromContent();
    _markDirty();
  });
  rich?.addEventListener('keydown', e => {
    if (e.key === 'Escape') rich.blur();
  });
  rich?.addEventListener('blur', () => {
    _syncEntryFromEditor();
    _refreshEntityPanelsFromContent();
    _refreshEditorContent();
  });

  document.querySelectorAll('[data-mood]').forEach(btn => {
    btn.addEventListener('click', () => {
      const value = btn.dataset.mood;
      if (_entry.mood_label === value) {
        _entry.mood_label = null;
        _entry.mood_score = null;
      } else {
        _entry.mood_label = value;
        _entry.mood_score = Number(btn.dataset.moodScore);
      }
      _refreshMoodControls();
      _markDirty();
    });
  });

  document.querySelectorAll('[data-score-field]').forEach(btn => {
    btn.addEventListener('click', () => {
      const field = btn.dataset.scoreField;
      const score = Number(btn.dataset.score);
      _entry[field] = Number(_entry[field]) === score ? null : score;
      _refreshScoreControls(field);
      _markDirty();
    });
  });

  document.getElementById('logbook-add-datapoint')?.addEventListener('click', () => _addDatapoint());
  document.querySelectorAll('[data-quick-data]').forEach(btn => {
    btn.addEventListener('click', () => _addDatapoint(btn.dataset.quickData, btn.dataset.quickLabel));
  });
  document.querySelectorAll('[data-remove-datapoint]').forEach(btn => {
    btn.addEventListener('click', () => {
      const index = Number(btn.dataset.removeDatapoint);
      _entry.datapoints.splice(index, 1);
      _renderDatapoints();
      _markDirty();
    });
  });
  document.querySelectorAll('.logbook-datapoint').forEach(row => {
    const index = Number(row.dataset.datapointIndex);
    const dp = _entry.datapoints[index];
    if (!dp) return;
    row.querySelector('.logbook-dp-label')?.addEventListener('input', e => {
      dp.label = e.target.value;
      dp.key = _cleanKey(e.target.value);
      _markDirty();
    });
    row.querySelector('.logbook-dp-value')?.addEventListener('input', e => {
      dp.value_text = e.target.value;
      _markDirty();
    });
    row.querySelector('.logbook-dp-number')?.addEventListener('input', e => {
      dp.value_number = e.target.value;
      _markDirty();
    });
    row.querySelector('.logbook-dp-unit')?.addEventListener('input', e => {
      dp.unit = e.target.value;
      _markDirty();
    });
  });

  const search = document.getElementById('logbook-entry-search');
  search?.addEventListener('input', () => {
    _search = search.value;
    clearTimeout(search._timer);
    search._timer = setTimeout(() => _loadEntries().then(_renderNavigator).catch(_showError), 250);
  });
  document.getElementById('logbook-person-filter')?.addEventListener('change', e => {
    _filterPerson = e.target.value;
    _loadEntries().then(_renderNavigator).catch(_showError);
  });
  document.getElementById('logbook-location-filter')?.addEventListener('change', e => {
    _filterLocation = e.target.value;
    _loadEntries().then(_renderNavigator).catch(_showError);
  });
  document.getElementById('logbook-mood-filter')?.addEventListener('change', e => {
    _filterMood = e.target.value;
    _loadEntries().then(_renderNavigator).catch(_showError);
  });
  const dataFilter = document.getElementById('logbook-data-filter');
  dataFilter?.addEventListener('input', () => {
    _filterDataKey = dataFilter.value;
    clearTimeout(dataFilter._timer);
    dataFilter._timer = setTimeout(() => _loadEntries().then(_renderNavigator).catch(_showError), 250);
  });

  _bindPeopleRowEvents();
  _bindLocationRowEvents();
  _bindPeopleDirectoryEvents();
  _bindLocationDirectoryEvents();
  document.querySelectorAll('[data-ai-mode]').forEach(btn => {
    btn.addEventListener('click', () => _runAI(btn.dataset.aiMode).catch(_showError));
  });
  document.getElementById('logbook-extract-facts')?.addEventListener('click', () => _extractFacts().catch(_showError));
  document.getElementById('logbook-apply-ai')?.addEventListener('click', () => _applyAIContent());
  document.getElementById('logbook-copy-ai')?.addEventListener('click', () => _copyAI());
  document.getElementById('logbook-clear-ai')?.addEventListener('click', () => {
    _aiPreview = null;
    _aiError = '';
    _render();
  });
  document.getElementById('logbook-apply-ai-mood')?.addEventListener('click', () => _applyAIMood());
  document.getElementById('logbook-add-ai-data')?.addEventListener('click', () => _addAIData());
  _bindAISuggestionEvents();
  _bindEntityLinkEvents();
  document.querySelectorAll('[data-accept-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.acceptConnection, 'accept').catch(_showError));
  });
  document.querySelectorAll('[data-hide-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.hideConnection, 'hide').catch(_showError));
  });
}

function _bindNavigatorEvents() {
  document.querySelectorAll('.logbook-nav [data-jump-date]').forEach(btn => {
    btn.addEventListener('click', () => _loadDate(btn.dataset.jumpDate).catch(_showError));
  });
  document.querySelectorAll('.logbook-nav [data-date]').forEach(btn => {
    btn.addEventListener('click', () => _loadDate(btn.dataset.date).catch(_showError));
  });
  document.getElementById('logbook-clear-filters')?.addEventListener('click', () => {
    _filterPerson = '';
    _filterLocation = '';
    _filterMood = '';
    _filterDataKey = '';
    _loadEntries().then(_renderNavigator).catch(_showError);
  });
  const search = document.getElementById('logbook-entry-search');
  search?.addEventListener('input', () => {
    _search = search.value;
    clearTimeout(search._timer);
    search._timer = setTimeout(() => _loadEntries().then(_renderNavigator).catch(_showError), 250);
  });
  document.getElementById('logbook-person-filter')?.addEventListener('change', e => {
    _filterPerson = e.target.value;
    _loadEntries().then(_renderNavigator).catch(_showError);
  });
  document.getElementById('logbook-location-filter')?.addEventListener('change', e => {
    _filterLocation = e.target.value;
    _loadEntries().then(_renderNavigator).catch(_showError);
  });
  document.getElementById('logbook-mood-filter')?.addEventListener('change', e => {
    _filterMood = e.target.value;
    _loadEntries().then(_renderNavigator).catch(_showError);
  });
  const dataFilter = document.getElementById('logbook-data-filter');
  dataFilter?.addEventListener('input', () => {
    _filterDataKey = dataFilter.value;
    clearTimeout(dataFilter._timer);
    dataFilter._timer = setTimeout(() => _loadEntries().then(_renderNavigator).catch(_showError), 250);
  });
}

function _bindDataEvents() {
  document.querySelectorAll('[data-remove-datapoint]').forEach(btn => {
    btn.addEventListener('click', () => {
      const index = Number(btn.dataset.removeDatapoint);
      _entry.datapoints.splice(index, 1);
      _renderDatapoints();
      _markDirty();
    });
  });
  document.querySelectorAll('.logbook-datapoint').forEach(row => {
    const index = Number(row.dataset.datapointIndex);
    const dp = _entry.datapoints[index];
    if (!dp) return;
    row.querySelector('.logbook-dp-label')?.addEventListener('input', e => {
      dp.label = e.target.value;
      dp.key = _cleanKey(e.target.value);
      _markDirty();
    });
    row.querySelector('.logbook-dp-value')?.addEventListener('input', e => {
      dp.value_text = e.target.value;
      _markDirty();
    });
    row.querySelector('.logbook-dp-number')?.addEventListener('input', e => {
      dp.value_number = e.target.value;
      _markDirty();
    });
    row.querySelector('.logbook-dp-unit')?.addEventListener('input', e => {
      dp.unit = e.target.value;
      _markDirty();
    });
  });
}

function _bindPeoplePanelEvents() {
  _bindPeopleRowEvents();
  _bindAISuggestionEvents();
  _bindEntityLinkEvents();
  document.querySelectorAll('[data-accept-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.acceptConnection, 'accept').catch(_showError));
  });
  document.querySelectorAll('[data-hide-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.hideConnection, 'hide').catch(_showError));
  });
  _bindPeopleDirectoryEvents();
}

function _bindLocationsPanelEvents() {
  _bindLocationRowEvents();
  _bindAISuggestionEvents();
  _bindLocationDirectoryEvents();
}

function _bindAISuggestionEvents() {
  document.querySelectorAll('[data-add-ai-person]').forEach(btn => {
    btn.addEventListener('click', () => _addAIEntity('person', Number(btn.dataset.addAiPerson)).catch(_showError));
  });
  document.querySelectorAll('[data-add-ai-location]').forEach(btn => {
    btn.addEventListener('click', () => _addAIEntity('location', Number(btn.dataset.addAiLocation)).catch(_showError));
  });
}

function _bindEntityLinkEvents(root = document) {
  root.querySelectorAll('[data-open-person]').forEach(link => {
    if (link.dataset.boundPersonLink === '1') return;
    link.dataset.boundPersonLink = '1';
    link.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      await _openPerson(link.dataset.openPerson);
    });
    link.addEventListener('keydown', async event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      event.stopPropagation();
      await _openPerson(link.dataset.openPerson);
    });
  });
  root.querySelectorAll('[data-open-location]').forEach(link => {
    if (link.dataset.boundLocationLink === '1') return;
    link.dataset.boundLocationLink = '1';
    link.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      await _openLocation(link.dataset.openLocation);
    });
    link.addEventListener('keydown', async event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      event.stopPropagation();
      await _openLocation(link.dataset.openLocation);
    });
  });
}

async function _openPerson(personId) {
  if (!personId) return;
  try {
    const atlas = await import('./logbookAtlas.js');
    await atlas.openAtlas({ tab: 'people', personId });
  } catch (_) {
    _filterPerson = personId;
    _activeTab = 'people';
    await _loadEntries();
    _render();
  }
}

async function _openLocation(locationId) {
  if (!locationId) return;
  try {
    const atlas = await import('./logbookAtlas.js');
    await atlas.openAtlas({ tab: 'locations', locationId });
  } catch (_) {
    _filterLocation = locationId;
    _activeTab = 'places';
    await _loadEntries();
    _render();
  }
}

function _bindPeopleRowEvents() {
  document.querySelectorAll('[data-insert-person]').forEach(btn => {
    btn.addEventListener('click', () => _insertMention(btn.dataset.insertPerson));
  });
  document.querySelectorAll('[data-filter-person]').forEach(btn => {
    btn.addEventListener('click', () => {
      _filterPerson = btn.dataset.filterPerson || '';
      _loadEntries().then(_renderNavigator).catch(_showError);
    });
  });
}

function _bindLocationRowEvents() {
  document.querySelectorAll('[data-insert-location]').forEach(btn => {
    btn.addEventListener('click', () => _insertLocation(btn.dataset.insertLocation));
  });
  document.querySelectorAll('[data-filter-location]').forEach(btn => {
    btn.addEventListener('click', () => {
      _filterLocation = btn.dataset.filterLocation || '';
      _loadEntries().then(_renderNavigator).catch(_showError);
    });
  });
}

function _bindPeopleDirectoryEvents() {
  const peopleSearch = document.getElementById('logbook-people-search');
  peopleSearch?.addEventListener('input', () => {
    _peopleSearch = peopleSearch.value;
    const list = document.getElementById('logbook-people-list');
    if (list) {
      list.innerHTML = _peopleRowsHtml();
      _bindPeopleRowEvents();
    }
  });
  document.getElementById('logbook-people-sort')?.addEventListener('change', e => {
    _peopleSort = e.target.value || 'recent';
    const list = document.getElementById('logbook-people-list');
    if (list) {
      list.innerHTML = _peopleRowsHtml();
      _bindPeopleRowEvents();
    }
  });
}

function _bindLocationDirectoryEvents() {
  const locationSearch = document.getElementById('logbook-location-search');
  locationSearch?.addEventListener('input', () => {
    _locationSearch = locationSearch.value;
    const list = document.getElementById('logbook-location-list');
    if (list) {
      list.innerHTML = _locationRowsHtml();
      _bindLocationRowEvents();
    }
  });
  document.getElementById('logbook-location-sort')?.addEventListener('change', e => {
    _locationSort = e.target.value || 'recent';
    const list = document.getElementById('logbook-location-list');
    if (list) {
      list.innerHTML = _locationRowsHtml();
      _bindLocationRowEvents();
    }
  });
  document.getElementById('logbook-create-location')?.addEventListener('click', () => _createLocation().catch(_showError));
}

function _renderPeoplePanel() {
  const panel = document.querySelector('.logbook-panel[data-mobile-section="people"]');
  if (!panel) return;
  panel.innerHTML = `${_peopleHtml()}${_connectionsHtml()}`;
  _bindPeoplePanelEvents();
}

function _renderLocationsPanel() {
  const panel = document.querySelector('.logbook-panel[data-mobile-section="places"]');
  if (!panel) return;
  panel.innerHTML = _locationsHtml();
  _bindLocationsPanelEvents();
}

function _renderNavigator() {
  const nav = document.querySelector('.logbook-nav');
  if (!nav) return;
  nav.innerHTML = _navigatorHtml();
  _bindNavigatorEvents();
}

function _renderHistoryPanel() {
  const panel = document.getElementById('logbook-history-panel');
  if (!panel) return;
  panel.outerHTML = _historyHtml();
  _bindHistoryEvents();
}

function _renderDatapoints() {
  const root = document.getElementById('logbook-datapoints');
  if (!root) return;
  root.innerHTML = _datapointsHtml();
  _bindDataEvents();
}

function _addDatapoint(key = '', label = '') {
  if (!_entry.datapoints) _entry.datapoints = [];
  _entry.datapoints.push({
    key: _cleanKey(key || label),
    label: label || key || '',
    value_text: '',
    value_number: null,
    unit: '',
    value_json: null,
    sort_order: _entry.datapoints.length,
  });
  _renderDatapoints();
  _markDirty();
}

function _mentionContext() {
  if (_editorMode !== 'raw') return null;
  const ta = document.getElementById('logbook-content');
  if (!ta) return null;
  const pos = ta.selectionStart ?? 0;
  const before = ta.value.slice(0, pos);
  const match = before.match(/(^|[\s(])@([A-Za-z0-9_-]{0,40})$/);
  if (!match) return null;
  return {
    textarea: ta,
    start: pos - match[2].length - 1,
    end: pos,
    query: match[2].toLowerCase(),
  };
}

function _locationContext() {
  if (_editorMode !== 'raw') return null;
  const ta = document.getElementById('logbook-content');
  if (!ta) return null;
  const pos = ta.selectionStart ?? 0;
  const before = ta.value.slice(0, pos);
  const match = before.match(/(^|[\s(])#([A-Za-z0-9_-]{0,40})$/);
  if (!match) return null;
  return {
    textarea: ta,
    start: pos - match[2].length - 1,
    end: pos,
    query: match[2].toLowerCase(),
  };
}

function _renderMentionMenu() {
  const menu = document.getElementById('logbook-mention-menu');
  const ctx = _mentionContext();
  const locCtx = ctx ? null : _locationContext();
  if (!menu || (!ctx && !locCtx)) {
    _hideMentionMenu();
    return;
  }
  const query = (ctx || locCtx).query;
  const matches = ctx
    ? _people.filter(p => {
        const names = [p.display_name, ...(p.aliases || [])].map(x => String(x || '').toLowerCase());
        return !query || names.some(name => name.startsWith(query) || name.includes(query));
      }).slice(0, 8)
    : _locations.filter(loc => {
        const names = [loc.display_name, ...(loc.aliases || [])].map(x => String(x || '').toLowerCase());
        return !query || names.some(name => name.startsWith(query) || name.includes(query));
      }).slice(0, 8);
  if (!matches.length) {
    _hideMentionMenu();
    return;
  }
  menu.classList.remove('hidden');
  menu.innerHTML = ctx
    ? matches.map(p => `<button type="button" data-mention-person="${_e(p.display_name)}">${_logbookIcon('person', 12)}<span>${_e(p.display_name)}</span></button>`).join('')
    : matches.map(loc => `<button type="button" data-mention-location="${_e(loc.display_name)}">${_logbookIcon('location', 12)}<span>${_e(loc.display_name)}</span></button>`).join('');
  menu.querySelectorAll('[data-mention-person], [data-mention-location]').forEach(btn => {
    btn.addEventListener('mousedown', e => {
      e.preventDefault();
      if (btn.dataset.mentionPerson) _replaceMention(ctx, btn.dataset.mentionPerson);
      else _replaceLocation(locCtx, btn.dataset.mentionLocation);
    });
  });
}

function _hideMentionMenu() {
  const menu = document.getElementById('logbook-mention-menu');
  if (menu) menu.classList.add('hidden');
}

function _mentionText(name) {
  const person = _personForLink('', name);
  const target = `person:${_slugName(person?.canonical_name || person?.display_name || name)}`;
  return `[${name}](${target})`;
}

function _locationText(name) {
  const location = _locationForLink('', name);
  const target = `place:${_slugName(location?.canonical_name || location?.display_name || name)}`;
  return `[${name}](${target})`;
}

function _selectionLinkParts(text) {
  const value = String(text || '');
  const leading = value.match(/^\s*/)?.[0] || '';
  const trailing = value.match(/\s*$/)?.[0] || '';
  const label = value
    .slice(leading.length, value.length - trailing.length)
    .replace(/[\[\]\r\n]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 160);
  return label ? { leading, label, trailing } : null;
}

function _selectionLinkTarget(kind, label) {
  if (kind === 'food') return 'data:food';
  if (kind === 'location') {
    const location = _locationForLink('', label);
    return `place:${_slugName(location?.canonical_name || location?.display_name || label)}`;
  }
  const person = _personForLink('', label);
  return `person:${_slugName(person?.canonical_name || person?.display_name || label)}`;
}

function _replaceRawSelectionWithLink(kind) {
  const ta = document.getElementById('logbook-content');
  if (!ta || ta.selectionStart === ta.selectionEnd) return false;
  const start = ta.selectionStart ?? 0;
  const end = ta.selectionEnd ?? start;
  const parts = _selectionLinkParts(ta.value.slice(start, end));
  if (!parts) return false;
  const target = _selectionLinkTarget(kind, parts.label);
  const linked = `${parts.leading}[${parts.label}](${target})${parts.trailing}`;
  ta.value = ta.value.slice(0, start) + linked + ta.value.slice(end);
  const pos = start + linked.length;
  ta.focus();
  ta.setSelectionRange(pos, pos);
  if (_entry) _entry.content = ta.value;
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _replaceRichSelectionWithLink(kind) {
  const editor = document.getElementById('logbook-rich-content');
  const selection = window.getSelection?.();
  if (!editor || !selection || !selection.rangeCount) return false;
  const range = selection.getRangeAt(0);
  const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
  const endsInside = range.endContainer === editor || editor.contains(range.endContainer);
  if (range.collapsed || !startsInside || !endsInside) return false;
  const parts = _selectionLinkParts(selection.toString());
  if (!parts) return false;
  const target = _selectionLinkTarget(kind, parts.label);
  const template = document.createElement('template');
  template.innerHTML = `${_e(parts.leading)}${_editorTokenHtml(parts.label, target)}${_e(parts.trailing)}`;
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
  _syncEntryFromEditor();
  _bindEntityLinkEvents(editor);
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _replaceRawSelectionWithText(start, end, text) {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
  const pos = start + text.length;
  ta.focus();
  ta.setSelectionRange(pos, pos);
  if (_entry) _entry.content = ta.value;
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _unlinkRawSelection() {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  const start = ta.selectionStart ?? 0;
  const end = ta.selectionEnd ?? start;
  const value = ta.value || '';
  LOGBOOK_LINK_RE.lastIndex = 0;
  for (const match of value.matchAll(LOGBOOK_LINK_RE)) {
    const matchStart = match.index ?? 0;
    const matchEnd = matchStart + match[0].length;
    if (matchStart <= start && matchEnd >= end) {
      return _replaceRawSelectionWithText(matchStart, matchEnd, match[1]);
    }
  }
  if (start === end) return false;
  const selected = value.slice(start, end);
  LOGBOOK_LINK_RE.lastIndex = 0;
  const unlinked = selected.replace(LOGBOOK_LINK_RE, '$1');
  if (unlinked === selected) return false;
  return _replaceRawSelectionWithText(start, end, unlinked);
}

function _tokenPlainText(token) {
  const label = token?.dataset?.label || '';
  if (label) return label;
  return String(token?.textContent || '').replace(/^[@#]/, '');
}

function _unlinkRichSelection() {
  const editor = document.getElementById('logbook-rich-content');
  if (!editor) return false;
  const selection = window.getSelection?.();
  const active = document.activeElement;
  const activeToken = active?.dataset?.logbookToken === '1' && editor.contains(active) ? active : null;
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
  tokens.forEach(token => {
    const textNode = document.createTextNode(_tokenPlainText(token));
    token.replaceWith(textNode);
    last = textNode;
  });
  if (last && selection) {
    const range = document.createRange();
    range.setStartAfter(last);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
  }
  editor.focus();
  _syncEntryFromEditor();
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _linkSelectedText(kind) {
  const linked = _editorMode === 'raw'
    ? _replaceRawSelectionWithLink(kind)
    : _replaceRichSelectionWithLink(kind);
  if (!linked) _setStatus('Select text first');
}

function _unlinkSelectedText() {
  const unlinked = _editorMode === 'raw'
    ? _unlinkRawSelection()
    : _unlinkRichSelection();
  if (!unlinked) _setStatus('Select a linked token first');
}

function _selectionInside(el) {
  const selection = window.getSelection?.();
  if (!selection || !selection.rangeCount || !el) return false;
  const node = selection.anchorNode;
  return Boolean(node && (node === el || el.contains(node)));
}

function _focusRichEditorEnd(editor) {
  if (!editor) return;
  editor.focus();
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  const selection = window.getSelection?.();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function _insertIntoRichEditor(html) {
  const editor = document.getElementById('logbook-rich-content');
  if (!editor) return false;
  if (!_selectionInside(editor)) _focusRichEditorEnd(editor);
  const selection = window.getSelection?.();
  if (!selection || !selection.rangeCount) return false;
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const template = document.createElement('template');
  template.innerHTML = html;
  const fragment = template.content;
  const last = fragment.lastChild;
  range.insertNode(fragment);
  if (last) {
    range.setStartAfter(last);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
  }
  editor.focus();
  _syncEntryFromEditor();
  _bindEntityLinkEvents(editor);
  _refreshEntityPanelsFromContent();
  return true;
}

function _replaceMention(ctx, name) {
  const ta = ctx.textarea;
  const text = _mentionText(name);
  ta.value = ta.value.slice(0, ctx.start) + text + ' ' + ta.value.slice(ctx.end);
  const pos = ctx.start + text.length + 1;
  ta.focus();
  ta.setSelectionRange(pos, pos);
  _entry.content = ta.value;
  _refreshEntityPanelsFromContent();
  _markDirty();
  _hideMentionMenu();
}

function _replaceLocation(ctx, name) {
  const ta = ctx.textarea;
  const text = _locationText(name);
  ta.value = ta.value.slice(0, ctx.start) + text + ' ' + ta.value.slice(ctx.end);
  const pos = ctx.start + text.length + 1;
  ta.focus();
  ta.setSelectionRange(pos, pos);
  _entry.content = ta.value;
  _refreshEntityPanelsFromContent();
  _markDirty();
  _hideMentionMenu();
}

function _insertMention(name) {
  if (!name) return;
  if (_editorMode !== 'raw') {
    _syncEntryFromEditor();
    const target = _mentionText(name).match(/\(([^)]+)\)$/)?.[1] || `person:${_slugName(name)}`;
    const prefix = _entry?.content && !/\s$/.test(_entry.content) ? ' ' : '';
    _insertIntoRichEditor(`${_e(prefix)}${_editorTokenHtml(name, target)} `);
    _markDirty();
    return;
  }
  const ta = document.getElementById('logbook-content');
  if (!ta) return;
  const insert = `${ta.value && !/\s$/.test(ta.value) ? ' ' : ''}${_mentionText(name)} `;
  const pos = ta.selectionStart ?? ta.value.length;
  ta.value = ta.value.slice(0, pos) + insert + ta.value.slice(pos);
  const next = pos + insert.length;
  ta.focus();
  ta.setSelectionRange(next, next);
  _entry.content = ta.value;
  _refreshEntityPanelsFromContent();
  _markDirty();
}

function _insertLocation(name) {
  if (!name) return;
  if (_editorMode !== 'raw') {
    _syncEntryFromEditor();
    const target = _locationText(name).match(/\(([^)]+)\)$/)?.[1] || `place:${_slugName(name)}`;
    const prefix = _entry?.content && !/\s$/.test(_entry.content) ? ' ' : '';
    _insertIntoRichEditor(`${_e(prefix)}${_editorTokenHtml(name, target)} `);
    _markDirty();
    return;
  }
  const ta = document.getElementById('logbook-content');
  if (!ta) return;
  const insert = `${ta.value && !/\s$/.test(ta.value) ? ' ' : ''}${_locationText(name)} `;
  const pos = ta.selectionStart ?? ta.value.length;
  ta.value = ta.value.slice(0, pos) + insert + ta.value.slice(pos);
  const next = pos + insert.length;
  ta.focus();
  ta.setSelectionRange(next, next);
  _entry.content = ta.value;
  _refreshEntityPanelsFromContent();
  _markDirty();
}

async function _createLocation() {
  const input = document.getElementById('logbook-location-new');
  const name = (input?.value || '').trim();
  if (!name) return;
  await createLocation(name);
  if (input) input.value = '';
  await _loadLocations();
  _renderLocationsPanel();
  _renderNavigator();
}

async function _runAI(mode) {
  if (_aiStatus?.available !== true) {
    _aiError = _aiStatus?.reason || 'No LLM provider configured.';
    _render();
    return;
  }
  if (_aiBusy) return;
  _aiBusy = true;
  _aiError = '';
  _aiPreview = null;
  _syncEntryFromEditor();
  _render();
  const content = _entry?.content || '';
  try {
    const result = await assistLogbook({
      entry_date: _date,
      content,
      mode,
      locale: (navigator.language || 'en').toLowerCase().startsWith('nl') ? 'nl' : 'en',
      current_entry: _entry || {},
    });
    _aiPreview = result;
  } catch (err) {
    _aiError = err.message || 'AI help failed. Your entry was not changed.';
  } finally {
    _aiBusy = false;
    _render();
  }
}

async function _extractFacts() {
  if (_aiStatus?.available !== true) {
    _aiError = _aiStatus?.reason || 'No LLM provider configured.';
    _render();
    return;
  }
  if (!_entry?.id || _dirty) {
    await _saveNow({ silent: true });
  }
  if (!_entry?.id) return;
  _aiBusy = true;
  _aiError = '';
  _render();
  try {
    const result = await analyzeEntry(_entry.id);
    _aiPreview = result;
    await Promise.all([_loadPeople(), _loadConnections(), _loadEntries()]);
  } catch (err) {
    _aiError = err.message || 'Extract facts failed.';
  } finally {
    _aiBusy = false;
    _render();
  }
}

async function _addAIEntity(kind, index) {
  if (!_entry?.id || _dirty) {
    await _saveNow({ silent: true });
  }
  if (!_entry?.id) return;
  const isPerson = kind === 'person';
  const list = isPerson ? (_aiPreview?.people_suggestions || []) : (_aiPreview?.location_suggestions || []);
  const item = list[index];
  if (!item) return;
  const knownPerson = isPerson ? _personSuggestionKnownPerson(item) : null;
  const hasFacts = isPerson ? _personSuggestionHasFacts(item) : false;
  const result = await applyEntrySuggestions(_entry.id, {
    people_suggestions: isPerson ? [item] : [],
    location_suggestions: isPerson ? [] : [item],
  });
  _entry = result.entry || _entry;
  await Promise.all([_loadPeople(), _loadLocations(), _loadConnections(), _loadEntries()]);
  _activeTab = isPerson ? 'people' : 'places';
  uiModule?.showToast?.(isPerson && knownPerson && hasFacts ? 'Person facts saved' : isPerson ? 'Person linked' : 'Place linked');
  _render();
}

function _applyAIContent() {
  if (!_aiPreview?.preview_content) return;
  const ta = document.getElementById('logbook-content');
  _entry.content = _aiPreview.preview_content;
  if (ta) ta.value = _entry.content;
  _refreshEditorContent();
  _markDirty();
  _activeTab = 'write';
  _render();
}

function _copyAI() {
  const p = _aiPreview || {};
  const text = p.preview_content || p.summary || p.reflection || (p.questions || []).join('\n') || '';
  if (!text) return;
  navigator.clipboard?.writeText(text).then(() => uiModule?.showToast?.('Copied')).catch(() => {});
}

function _addAIData() {
  const items = _aiPreview?.datapoint_suggestions || [];
  if (!items.length) return;
  if (!_entry.datapoints) _entry.datapoints = [];
  for (const item of items) {
    _entry.datapoints.push({
      key: _cleanKey(item.key || item.label),
      label: item.label || item.key || '',
      value_text: item.value_text || '',
      value_number: item.value_number ?? null,
      unit: item.unit || '',
      value_json: item.value_json ?? null,
      sort_order: _entry.datapoints.length,
    });
  }
  _activeTab = 'data';
  _markDirty();
  _render();
}

function _applyAIMood() {
  const mood = _aiPreview?.mood_suggestion;
  if (!mood) return;
  _entry.mood_label = mood.label || null;
  _entry.mood_score = mood.score ? Number(mood.score) : null;
  _activeTab = 'mood';
  _markDirty();
  _render();
}

async function _connectionAction(id, action) {
  await updateConnection(id, action);
  await Promise.all([_loadConnections(), _loadPeople()]);
  _render();
}

function _showError(err) {
  uiModule?.showError?.(err?.message || String(err || 'Logbook error'));
}

export async function openLogbook() {
  if (Modals.isMinimized(MODAL_ID)) {
    Modals.restore(MODAL_ID);
    return;
  }
  _open = true;
  _renderShell().classList.remove('hidden');
  await _loadDate(_date).catch(_showError);
}

export async function openLogbookDate(date) {
  const targetDate = String(date || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
    return openLogbook();
  }
  if (Modals.isMinimized(MODAL_ID)) {
    Modals.restore(MODAL_ID);
  }
  _open = true;
  _renderShell().classList.remove('hidden');
  await _loadDate(targetDate).catch(_showError);
}

export function closeLogbook() {
  _open = false;
  if (_saveTimer) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
  }
  if (_dirty) {
    _saveNow({ silent: true }).catch(() => {});
  }
  document.getElementById(MODAL_ID)?.remove();
  try { Modals.unregister(MODAL_ID); } catch (_) {}
}

export function isLogbookOpen() {
  return _open && !!document.getElementById(MODAL_ID);
}

export function toggleLogbook() {
  if (Modals.toggle(MODAL_ID)) return;
  if (isLogbookOpen()) closeLogbook();
  else openLogbook();
}

const logbookModule = { openLogbook, openLogbookDate, closeLogbook, toggleLogbook, isLogbookOpen };
window.logbookModule = logbookModule;
export default logbookModule;
