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
  estimateLogbookAI,
  getAIStatus,
  getEntry,
  getEntryRevision,
  getLogbookAIUsage,
  listConnections,
  listEntryRevisions,
  listEntries,
  listLocations,
  listPeople,
  restoreEntryRevision,
  saveEntry,
  updateConnection,
} from './logbook/api.js';
import {
  entityAutocompleteContext as _entityAutocompleteContext,
  entityAutocompleteMatches as _entityAutocompleteMatches,
} from './logbook/autocomplete.js';
import { MODAL_ID, MOODS, QUICK_DATA, SAVE_DELAY } from './logbook/constants.js';
import {
  currentEntitiesFromContent as _currentEntitiesFromContentForLists,
  entityListSignature as _entityListSignature,
  linkTargetForEntity as _linkTargetForEntity,
  linkKind as _linkKind,
  locationForLink as _locationForLinkIn,
  locationMarkdown as _locationMarkdown,
  mentionMarkdown as _mentionMarkdown,
  personForLink as _personForLinkIn,
  selectionLinkParts as _selectionLinkParts,
  selectionLinkTarget as _selectionLinkTargetForLists,
  slugName as _slugName,
} from './logbook/entities.js';
import {
  escapeRichEditorToken as _escapeRichEditorTokenIn,
  focusRichEditorEnd as _focusRichEditorEnd,
  insertMarkdownHorizontalRule as _insertMarkdownHorizontalRule,
  linkedSelectionText as _linkedSelectionText,
  renderEditorText as _renderEditorText,
  replaceRichSelectionWithLink as _replaceRichSelectionWithLinkIn,
  richEditorToMarkdown as _richEditorToMarkdown,
  selectionInside as _selectionInside,
  toggleMarkdownCodeBlock as _toggleMarkdownCodeBlock,
  toggleMarkdownHeading as _toggleMarkdownHeading,
  toggleMarkdownLinePrefix as _toggleMarkdownLinePrefix,
  toggleMarkdownOrderedList as _toggleMarkdownOrderedList,
  toggleMarkdownSelectionFormat as _toggleMarkdownSelectionFormat,
  unlinkMarkdownSelection as _unlinkMarkdownSelection,
  unlinkRichSelection as _unlinkRichSelectionIn,
  wrapRichSelection as _wrapRichSelection,
} from './logbook/editor.js';
import { iconBook as _iconBook, logbookIcon as _logbookIcon } from './logbook/icons.js';
import {
  bindDirectoryControls as _bindDirectoryControls,
  bindDirectoryRowActions as _bindDirectoryRowActions,
  directoryMeta as _directoryMeta,
  renderLocationRowsHtml as _renderLocationRowsHtml,
  renderLocationsPanelHtml as _renderLocationsPanelHtml,
  renderPeoplePanelHtml as _renderPeoplePanelHtml,
  renderPeopleRowsHtml as _renderPeopleRowsHtml,
} from './logbook/panels.js';
import {
  cleanKey as _cleanKey,
  dateAdd as _dateAdd,
  dateLabel as _dateLabel,
  escapeHtml as _e,
  today as _today,
} from './logbook/utils.js';

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
let _aiEstimate = null;
let _aiUsageSummary = null;
let _aiSelectedMode = 'structure_day';
let _aiEstimateBusy = false;
let _aiEstimateTimer = null;
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
let _selectionMenu = null;
let _entityLinkChooser = null;

const AI_MODE_GROUPS = [
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
let _activeEditorToken = null;
let _floatingEntityCard = null;
let _floatingEntityCardSource = null;
let _floatingEntityCardHideTimer = null;

function _setStatus(text) {
  _saveStatus = text;
  const el = document.getElementById('logbook-save-status');
  if (el) el.textContent = text;
}

function _markDirty() {
  _dirty = true;
  _setStatus('Unsaved');
  _refreshTokenEstimate();
  _scheduleAIEstimateRefresh();
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

function _aiLocale() {
  return (navigator.language || 'en').toLowerCase().startsWith('nl') ? 'nl' : 'en';
}

function _aiRequestPayload(mode = _aiSelectedMode) {
  const requestMode = mode === 'extract_facts' ? 'extract_all' : mode;
  return {
    entry_date: _date,
    content: _entry?.content || '',
    mode: requestMode,
    locale: _aiLocale(),
    current_entry: _entry || {},
  };
}

async function _loadAIUsageSummary({ render = false } = {}) {
  try {
    _aiUsageSummary = await getLogbookAIUsage();
    if (_aiPreview?.usage && _aiUsageSummary) {
      _aiPreview.usage.billing = _aiUsageSummary.billing || _aiPreview.usage.billing;
      _aiPreview.usage.day = _aiUsageSummary.day || _aiPreview.usage.day;
      _aiPreview.usage.month = _aiUsageSummary.month || _aiPreview.usage.month;
    }
  } catch (_) {
    _aiUsageSummary = null;
  }
  if (render) _renderAIPanel();
}

async function _loadAIEstimate(mode = _aiSelectedMode, { render = false } = {}) {
  if (_aiStatus?.available !== true) {
    _aiEstimate = null;
    if (render) _renderAIPanel();
    return;
  }
  _aiEstimateBusy = true;
  if (render) _renderAIPanel();
  try {
    _aiEstimate = await estimateLogbookAI(_aiRequestPayload(mode));
  } catch (_) {
    _aiEstimate = null;
  } finally {
    _aiEstimateBusy = false;
    if (render) _renderAIPanel();
  }
}

function _scheduleAIEstimateRefresh() {
  if (!_open || _aiStatus?.available !== true) return;
  if (_aiEstimateTimer) clearTimeout(_aiEstimateTimer);
  _aiEstimateTimer = setTimeout(() => {
    _aiEstimateTimer = null;
    _loadAIEstimate(_aiSelectedMode, { render: true }).catch(() => {});
  }, 700);
}

async function _loadDate(date) {
  if (_dirty) {
    try { await _saveNow({ silent: true }); } catch (_) {}
  }
  _date = date;
  _aiPreview = null;
  _aiError = '';
  _aiEstimate = null;
  await Promise.all([_loadEntry(_date), _loadPeople(), _loadLocations(), _loadConnections(), _loadEntries(), _loadAIStatus(), _loadAIUsageSummary()]);
  await _loadAIEstimate(_aiSelectedMode);
  _render();
}

function _personForLink(target, label = '') {
  return _personForLinkIn(_people, target, label);
}

function _locationForLink(target, label = '', { includeHidden = false } = {}) {
  return _locationForLinkIn(_locations, target, label, { includeHidden });
}

function _currentEntitiesFromContent(content) {
  return _currentEntitiesFromContentForLists(content, { people: _people, locations: _locations });
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

function _personCardText(value, maxLength = 150) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text || text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 3)).trim()}...`;
}

function _personCardSectionHtml(title, contentHtml) {
  if (!contentHtml) return '';
  return `
    <span class="logbook-person-card-section">
      <span class="logbook-person-card-section-title">${_e(title)}</span>
      ${contentHtml}
    </span>
  `;
}

function _personCardStatHtml(iconHtml, label, value) {
  if (value === '' || value === null || value === undefined) return '';
  return `
    <span class="logbook-person-card-stat">
      ${iconHtml}
      <span><em>${_e(label)}</em><strong>${_e(value)}</strong></span>
    </span>
  `;
}

function _personCardStatsHtml(person) {
  if (!person?.id) return '';
  const stats = [
    person.last_mentioned ? _personCardStatHtml(_logbookIcon('quote', 12), 'Last seen', person.last_mentioned) : '',
  ].filter(Boolean).join('');
  return stats ? `<span class="logbook-person-card-stats">${stats}</span>` : '';
}

function _personCardAliasesHtml(person) {
  const aliases = Array.isArray(person?.aliases)
    ? person.aliases.map(alias => _personCardText(alias, 44)).filter(Boolean)
    : [];
  if (!aliases.length) return '';
  const shown = aliases.slice(0, 4).map(alias => `<span>${_e(alias)}</span>`).join('');
  const extra = Math.max(0, aliases.length - 4);
  return _personCardSectionHtml('Also known as', `
    <span class="logbook-person-card-aliases">
      ${shown}${extra ? `<span>+${extra}</span>` : ''}
    </span>
  `);
}

function _personCardContextHtml(person) {
  const rows = [];
  const notes = _personCardText(person?.notes, 170);
  const context = _personCardText(person?.llm_context, 190);
  if (notes) rows.push(`<span><strong>Notes</strong><em>${_e(notes)}</em></span>`);
  if (context && context !== notes) rows.push(`<span><strong>Context</strong><em>${_e(context)}</em></span>`);
  if (!rows.length) return '';
  return _personCardSectionHtml('Details', `<span class="logbook-person-card-detail-list">${rows.join('')}</span>`);
}

function _personCardContactHtml(person, snapshot, name) {
  const emails = Array.isArray(snapshot.emails) ? snapshot.emails : (snapshot.email ? [snapshot.email] : []);
  const phones = Array.isArray(snapshot.phones) ? snapshot.phones : (snapshot.phone ? [snapshot.phone] : []);
  const rows = [];
  const contactName = _personCardText(snapshot.name, 64);
  if (contactName && contactName !== name) rows.push(['Contact', contactName]);
  if (emails.length) rows.push(['Email', `${_personCardText(emails[0], 80)}${emails.length > 1 ? ` +${emails.length - 1}` : ''}`]);
  if (phones.length) rows.push(['Phone', `${_personCardText(phones[0], 36)}${phones.length > 1 ? ` +${phones.length - 1}` : ''}`]);
  if (person?.contact_source) rows.push(['Source', _personCardText(person.contact_source, 42)]);
  if (!rows.length) return '';
  const html = rows.map(([label, value]) => `
    <span class="logbook-person-card-info-row">
      <span>${_e(label)}</span>
      <strong>${_e(value)}</strong>
    </span>
  `).join('');
  return _personCardSectionHtml('Contact', `<span class="logbook-person-card-info">${html}</span>`);
}

function _personCardHtml(person, label, target) {
  const snapshot = person?.contact_snapshot || {};
  const image = _safePersonImage(snapshot.photo || snapshot.avatar || snapshot.image || snapshot.image_url || snapshot.picture);
  const name = person?.display_name || label || target || 'Person';
  const surface = String(label || '').trim();
  const surfaceNote = surface && surface.toLowerCase() !== String(name).toLowerCase()
    ? `<span class="logbook-person-card-note"><strong>Text in entry:</strong> ${_e(surface)}</span>`
    : '';
  const relation = person?.relationship_label || '';
  const initial = String(name).trim().slice(0, 1).toUpperCase() || '?';
  const connections = _personConnectionsPreviewHtml(person, { limit: 3 });
  const facts = _personFactsPreviewHtml(person, { limit: 3 });
  return `
    <span class="logbook-person-card" role="tooltip">
      <span class="logbook-person-card-head">
        ${image ? `<img src="${_e(image)}" alt="">` : `<span class="logbook-person-initial logbook-card-icon" title="${_e(initial)}">${_logbookIcon('person', 16)}</span>`}
        <span><strong>${_e(name)}</strong>${relation ? `<em>${_e(relation)}</em>` : ''}</span>
      </span>
      ${surfaceNote}
      ${_personCardStatsHtml(person)}
      ${facts ? _personCardSectionHtml('Known facts', facts) : ''}
      ${connections ? _personCardSectionHtml('Connections', connections) : ''}
      ${_personCardAliasesHtml(person)}
      ${_personCardContextHtml(person)}
      ${_personCardContactHtml(person, snapshot, name)}
      ${person?.id ? '<span class="logbook-person-card-link">Linked person</span>' : '<span class="logbook-person-card-link">Apply or save to create this person</span>'}
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
  const surface = String(label || '').trim();
  const surfaceNote = surface && surface !== name
    ? `<span class="logbook-person-card-note"><strong>Text in entry:</strong> ${_e(surface)}</span>`
    : '';
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
      ${surfaceNote}
      ${address ? `<span class="logbook-person-card-note">${_e(address)}</span>` : ''}
      ${coords ? `<span class="logbook-person-card-note">${_e(coords)}</span>` : ''}
      ${notes ? `<span class="logbook-person-card-note">${_e(notes)}</span>` : ''}
      ${location?.id ? '<span class="logbook-person-card-link">Linked place</span>' : '<span class="logbook-person-card-link">Save to create this place</span>'}
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

function _isEntityMarkdownTarget(target) {
  const value = String(target || '').trim();
  return /^(?:person|place|location|data|food):[A-Za-z0-9_-]{2,100}$/i.test(value)
    || /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(value);
}

function _normalizeMarkdownUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith('#')) return raw;
  if (/^[^\s@/]+\.[^\s@/]{2,}(?:[/?#].*)?$/i.test(raw)) return `https://${raw}`;
  return raw;
}

function _safeMarkdownHref(value) {
  const raw = _normalizeMarkdownUrl(value);
  if (!raw) return '';
  if (raw.startsWith('#')) return /^#[A-Za-z0-9_-]*$/.test(raw) ? raw : '';
  try {
    const parsed = new URL(raw, window.location.origin);
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? parsed.href : '';
  } catch (_) {
    return '';
  }
}

function _renderMarkdownAnchor(label, target, { editor = false } = {}) {
  const href = _safeMarkdownHref(target);
  const cls = editor ? 'logbook-editor-link' : 'logbook-person-link logbook-markdown-link';
  if (!href) {
    return `<span class="${editor ? 'logbook-editor-link logbook-editor-link-invalid' : 'logbook-markdown-link logbook-markdown-link-invalid'}" data-logbook-markdown-link="1" data-href="${_e(target)}">${_e(label)}</span>`;
  }
  const dataAttrs = editor ? ` data-logbook-markdown-link="1" data-href="${_e(_normalizeMarkdownUrl(target))}"` : '';
  return `<a class="${cls}" href="${_e(href)}"${dataAttrs} target="_blank" rel="noopener noreferrer">${_e(label)}</a>`;
}

function _renderEditorMarkdownLink(label, target) {
  return _isEntityMarkdownTarget(target)
    ? _editorTokenHtml(label, target)
    : _renderMarkdownAnchor(label, target, { editor: true });
}

function _renderDisplayMarkdownLink(label, target) {
  if (!_isEntityMarkdownTarget(target)) return _renderMarkdownAnchor(label, target);
  const kind = _linkKind(target);
  if (kind === 'location') return _renderLocationLink(label, target);
  if (kind === 'data') return _renderDataLink(label, target);
  return _renderPersonLink(label, target);
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
  let openAttrs = ' role="text" tabindex="0"';
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
  return _renderEditorText(content, { escapeHtml: _e, renderLink: _renderEditorMarkdownLink });
}

function _renderLogbookText(content) {
  const html = _renderEditorText(content, { escapeHtml: _e, renderLink: _renderDisplayMarkdownLink });
  return html || '<span class="logbook-empty">No text yet.</span>';
}

function _plainLogbookSnippet(content) {
  return String(content || '')
    .replace(/\[([^\]\n]{1,300})\]\(([^)\n]{1,700})\)/g, '$1')
    .replace(/(\*+|_+)([^\n*_]+?)\1/g, '$2')
    .replace(/~~([^~\n]+?)~~/g, '$1')
    .replace(/`([^`\n]+?)`/g, '$1');
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

function _formatCompactTokens(count) {
  const value = Number(count || 0);
  if (!Number.isFinite(value) || value <= 0) return '0';
  if (value >= 1000000) return `${(value / 1000000).toFixed(value >= 10000000 ? 0 : 1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k`;
  return value.toLocaleString();
}

function _formatMoneyDisplay(value, fallback = '') {
  const text = String(value || '').trim();
  return text || fallback;
}

function _aiIcon(kind, size = 14) {
  return kind === 'book' ? _iconBook(size) : _logbookIcon(kind, size);
}

function _aiEstimateData() {
  return _aiEstimate?.estimate || _aiPreview?.usage?.estimate || null;
}

function _aiUsageData() {
  const usage = _aiPreview?.usage || {};
  return {
    billing: usage.billing || _aiUsageSummary?.billing || _aiEstimate?.billing || {},
    day: usage.day || _aiUsageSummary?.day || _aiEstimate?.day || null,
    month: usage.month || _aiUsageSummary?.month || _aiEstimate?.month || null,
  };
}

function _aiActualUsageData() {
  return _aiPreview?.usage?.actual || null;
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
  _closeSelectionMenu();
  _closeEntityLinkChooser();
  _closeFloatingEntityCard();
  _clearActiveEditorToken();
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
          ${entry.snippet ? `<span class="logbook-day-snippet">${_e(_plainLogbookSnippet(entry.snippet))}</span>` : ''}
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
    <div class="logbook-link-toolbar" role="toolbar" aria-label="Format selected text">
      <button type="button" class="logbook-format-button" data-logbook-format="bold" title="Bold" aria-label="Bold">${_logbookIcon('bold', 13)}</button>
      <button type="button" class="logbook-format-button" data-logbook-format="italic" title="Italic" aria-label="Italic">${_logbookIcon('italic', 13)}</button>
      <button type="button" class="logbook-format-button" data-logbook-format="strike" title="Strikethrough" aria-label="Strikethrough">${_logbookIcon('strike', 13)}</button>
      <span class="logbook-toolbar-sep" aria-hidden="true"></span>
      <button type="button" class="logbook-format-button logbook-format-text" data-logbook-format="h1" title="Heading 1" aria-label="Heading 1">H1</button>
      <button type="button" class="logbook-format-button logbook-format-text" data-logbook-format="h2" title="Heading 2" aria-label="Heading 2">H2</button>
      <button type="button" class="logbook-format-button logbook-format-text" data-logbook-format="h3" title="Heading 3" aria-label="Heading 3">H3</button>
      <button type="button" class="logbook-format-button" data-logbook-format="quote" title="Quote" aria-label="Quote">${_logbookIcon('quote', 13)}</button>
      <button type="button" class="logbook-format-button" data-logbook-format="ul" title="Bullet list" aria-label="Bullet list">${_logbookIcon('list', 13)}</button>
      <button type="button" class="logbook-format-button" data-logbook-format="ol" title="Numbered list" aria-label="Numbered list">${_logbookIcon('orderedList', 13)}</button>
      <span class="logbook-toolbar-sep" aria-hidden="true"></span>
      <button type="button" class="logbook-format-button" data-logbook-format="code" title="Inline code" aria-label="Inline code">${_logbookIcon('code', 13)}</button>
      <button type="button" class="logbook-format-button" data-logbook-format="codeblock" title="Code block" aria-label="Code block">${_logbookIcon('codeBlock', 13)}</button>
      <button type="button" class="logbook-format-button" data-logbook-format="hr" title="Horizontal rule" aria-label="Horizontal rule">${_logbookIcon('hr', 13)}</button>
      <button type="button" class="logbook-format-button" data-logbook-format="link" title="Link" aria-label="Link">${_logbookIcon('link', 13)}</button>
      <span class="logbook-toolbar-sep" aria-hidden="true"></span>
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
  return _renderPeoplePanelHtml({
    entry: _entry,
    aiPreview: _aiPreview,
    people: _people,
    search: _peopleSearch,
    sort: _peopleSort,
    activePersonId: _filterPerson,
    escapeHtml: _e,
    icon: _logbookIcon,
    personSuggestionMeta: _personSuggestionMeta,
    personSuggestionActionLabel: _personSuggestionActionLabel,
    renderFactsPreview: _personFactsPreviewHtml,
    renderConnectionsPreview: _personConnectionsPreviewHtml,
  });
}

function _peopleRowsHtml() {
  return _renderPeopleRowsHtml({
    people: _people,
    search: _peopleSearch,
    sort: _peopleSort,
    activePersonId: _filterPerson,
    escapeHtml: _e,
    icon: _logbookIcon,
    renderFactsPreview: _personFactsPreviewHtml,
    renderConnectionsPreview: _personConnectionsPreviewHtml,
  });
}

function _locationsHtml() {
  return _renderLocationsPanelHtml({
    entry: _entry,
    aiPreview: _aiPreview,
    locations: _locations,
    search: _locationSearch,
    sort: _locationSort,
    activeLocationId: _filterLocation,
    escapeHtml: _e,
    icon: _logbookIcon,
  });
}

function _locationRowsHtml() {
  return _renderLocationRowsHtml({
    locations: _locations,
    search: _locationSearch,
    sort: _locationSort,
    activeLocationId: _filterLocation,
    escapeHtml: _e,
    icon: _logbookIcon,
  });
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

function _aiModeMeta(mode) {
  for (const group of AI_MODE_GROUPS) {
    const found = group.items.find(item => item.mode === mode);
    if (found) return found;
  }
  return { mode, label: mode.replace(/_/g, ' '), detail: '', icon: 'person' };
}

function _aiMetricHtml(label, value, meta = '') {
  return `
    <div class="logbook-ai-metric">
      <span>${_e(label)}</span>
      <strong>${_e(value)}</strong>
      ${meta ? `<em>${_e(meta)}</em>` : ''}
    </div>
  `;
}

function _aiUsageMeterHtml() {
  const estimate = _aiEstimateData();
  const actual = _aiActualUsageData();
  const usage = _aiUsageData();
  const billing = usage.billing || {};
  const day = usage.day || {};
  const month = usage.month || {};
  const estimatedInput = estimate?.input_tokens ?? _estimateEntryTokens(_entry?.content || '');
  const estimatedOutput = estimate?.max_output_tokens ?? 0;
  const estimatedTotal = estimate?.total_tokens ?? (estimatedInput + estimatedOutput);
  const estimateCost = estimate?.cost || {};
  const runCost = billing.enabled
    ? _formatMoneyDisplay(estimateCost.display, estimateCost.known ? '$0.00' : 'Unknown')
    : 'Billing off';
  const billingLabel = billing.enabled
    ? (billing.usage_ledger_enabled === false ? 'Billing on, ledger off' : 'Billing on')
    : 'Billing off';
  const dayCost = billing.enabled ? _formatMoneyDisplay(day.display, '$0.00') : '';
  const monthCost = billing.enabled ? _formatMoneyDisplay(month.display, '$0.00') : '';
  const actualMeta = actual?.total_tokens
    ? `${_formatCompactTokens(actual.total_tokens)} last run${actual.cost?.display && billing.enabled ? ` | ${actual.cost.display}` : ''}`
    : (_aiEstimateBusy ? 'Updating...' : 'Ready');
  return `
    <div class="logbook-ai-meter">
      <div class="logbook-ai-meter-head">
        <span>Usage</span>
        <strong>${_e(billingLabel)}</strong>
      </div>
      <div class="logbook-ai-meter-grid">
        ${_aiMetricHtml('Prompt', _formatCompactTokens(estimatedInput), 'input')}
        ${_aiMetricHtml('Output cap', estimatedOutput ? _formatCompactTokens(estimatedOutput) : '0', 'max')}
        ${_aiMetricHtml('Run total', _formatCompactTokens(estimatedTotal), actualMeta)}
        ${_aiMetricHtml('Run cost', runCost, estimateCost.known || !billing.enabled ? '' : 'pricing missing')}
      </div>
      <div class="logbook-ai-ledger">
        <span><strong>Today</strong>${_e(_formatCompactTokens(day.total_tokens || 0))} tokens${dayCost ? ` | ${_e(dayCost)}` : ''}</span>
        <span><strong>Month</strong>${_e(_formatCompactTokens(month.total_tokens || 0))} tokens${monthCost ? ` | ${_e(monthCost)}` : ''}</span>
      </div>
    </div>
  `;
}

function _aiModeGroupsHtml(disabled, disabledTitle) {
  return AI_MODE_GROUPS.map(group => `
    <div class="logbook-ai-command-group">
      <div class="logbook-ai-command-title">${_e(group.label)}</div>
      <div class="logbook-ai-command-grid">
        ${group.items.map(item => {
          const active = _aiSelectedMode === item.mode;
          const primary = item.primary ? ' primary' : '';
          const activeCls = active ? ' active' : '';
          return `
            <button type="button" class="logbook-ai-command${primary}${activeCls}" data-ai-mode="${_e(item.mode)}"${disabled}${disabledTitle}>
              <span class="logbook-ai-command-icon">${_aiIcon(item.icon, 14)}</span>
              <span class="logbook-ai-command-copy">
                <strong>${_e(item.label)}</strong>
                <em>${_e(item.detail)}</em>
              </span>
            </button>
          `;
        }).join('')}
      </div>
    </div>
  `).join('');
}

function _aiRunControlsHtml(disabled, disabledTitle) {
  const selected = _aiModeMeta(_aiSelectedMode);
  const isFactsMode = _aiSelectedMode === 'extract_facts';
  const label = isFactsMode ? 'Run fact extraction' : 'Run AI help';
  const detail = isFactsMode ? 'Uses the saved entry' : `${selected.label} | ${selected.detail}`;
  return `
    <div class="logbook-ai-runbar">
      <div class="logbook-ai-runbar-copy">
        <span>Selected</span>
        <strong>${_e(selected.label)}</strong>
        <em>${_e(detail)}</em>
      </div>
      <button type="button" class="cal-btn cal-btn-primary logbook-ai-run-btn" id="logbook-run-ai"${disabled}${disabledTitle}>${_e(label)}</button>
    </div>
  `;
}

function _aiRunReceiptHtml() {
  const usage = _aiPreview?.usage;
  if (!usage) return '';
  const actual = usage.actual || {};
  const billing = usage.billing || {};
  const mode = _aiModeMeta(usage.mode || _aiSelectedMode);
  const state = usage.fallback ? 'Local fallback' : usage.cached ? 'Cached result' : 'Last run';
  const cost = billing.enabled
    ? _formatMoneyDisplay(actual.cost?.display, actual.cost?.known ? '$0.00' : 'Unknown cost')
    : 'Billing off';
  const source = actual.usage_source ? ` | ${actual.usage_source}` : '';
  return `
    <div class="logbook-ai-receipt">
      <div>
        <strong>${_e(state)}</strong>
        <span>${_e(mode.label)}${_e(source)}</span>
      </div>
      <div>
        <strong>${_e(_formatCompactTokens(actual.total_tokens || 0))}</strong>
        <span>${_e(cost)}</span>
      </div>
    </div>
  `;
}

function _aiHtml() {
  const aiAvailable = _aiStatus?.available === true;
  const disabled = aiAvailable ? '' : ' disabled aria-disabled="true"';
  const disabledTitle = aiAvailable ? '' : ` title="${_e(_aiStatus?.reason || 'No LLM provider configured')}"`;
  const preview = _aiPreview
    ? _aiPreviewHtml()
    : aiAvailable
      ? '<div class="logbook-empty">AI previews appear here.</div>'
      : '<div class="logbook-empty">Manual writing still works. Configure a default or utility LLM provider to enable AI help.</div>';
  return `
    <div class="logbook-section-head logbook-ai-head">
      <h5>AI help</h5>
      ${aiAvailable ? `<span class="logbook-ai-model" title="${_e(_aiStatus.model || '')}">${_e(_aiStatus.model || 'AI ready')}</span>` : ''}
    </div>
    <div class="logbook-ai-control-box">
      ${aiAvailable ? _aiUsageMeterHtml() : `<div class="logbook-ai-disabled">AI help is off: ${_e(_aiStatus?.reason || 'No LLM provider configured')}.</div>`}
      <div class="logbook-ai-actions">${_aiModeGroupsHtml(disabled, disabledTitle)}</div>
      ${aiAvailable ? _aiRunControlsHtml(disabled, disabledTitle) : ''}
      ${_aiBusy ? '<div class="logbook-ai-status">Thinking...</div>' : ''}
      ${_aiError ? `<div class="logbook-ai-error">${_e(_aiError)}</div>` : ''}
    </div>
    <section class="logbook-ai-results" aria-label="AI results">
      <div class="logbook-section-head"><h5>Results</h5></div>
      ${_aiRunReceiptHtml()}
      <div id="logbook-ai-preview" class="logbook-ai-preview">${preview}</div>
    </section>
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

  document.querySelectorAll('[data-logbook-format]').forEach(btn => {
    btn.addEventListener('mousedown', event => event.preventDefault());
    btn.addEventListener('click', () => _formatSelectedText(btn.dataset.logbookFormat || '').catch(_showError));
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
  content?.addEventListener('contextmenu', _openSelectionContextMenu);

  const rich = document.getElementById('logbook-rich-content');
  rich?.addEventListener('pointerdown', e => {
    const token = _editorTokenFromEvent(e, rich);
    if (token) _selectEditorToken(token, e);
    else _clearActiveEditorToken();
  }, true);
  rich?.addEventListener('mousedown', e => {
    const token = _editorTokenFromEvent(e, rich);
    if (token) _selectEditorToken(token, e);
    else _clearActiveEditorToken();
  });
  rich?.addEventListener('input', () => {
    _syncEntryFromEditor();
    _refreshEntityPanelsFromContent();
    _markDirty();
  });
  rich?.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      rich.blur();
      return;
    }
    if (e.key === 'Tab') {
      if (_escapeActiveRichToken({ side: e.shiftKey ? 'before' : 'after', ensureSpace: !e.shiftKey })) {
        e.preventDefault();
      }
      return;
    }
    if (e.key === ' ' || e.key === 'Spacebar') {
      if (_activeEditorToken && rich.contains(_activeEditorToken) && _escapeActiveRichToken({ side: 'after', ensureSpace: true })) {
        e.preventDefault();
      }
    }
  });
  rich?.addEventListener('blur', event => {
    _syncEntryFromEditor();
    _refreshEntityPanelsFromContent();
    const focusStayedInEditor = event.relatedTarget && rich.contains(event.relatedTarget);
    const tokenSelected = _activeEditorToken && rich.contains(_activeEditorToken);
    if (!_entityLinkChooser && !focusStayedInEditor && !tokenSelected) _refreshEditorContent();
  });
  rich?.addEventListener('contextmenu', _openSelectionContextMenu);

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
  _bindAIEvents();
  document.querySelectorAll('[data-accept-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.acceptConnection, 'accept').catch(_showError));
  });
  document.querySelectorAll('[data-hide-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.hideConnection, 'hide').catch(_showError));
  });
}

function _selectedTextInsideLogbookEditor(target) {
  if (_editorMode === 'raw') {
    const ta = document.getElementById('logbook-content');
    if (!ta || target !== ta) return '';
    const start = ta.selectionStart ?? 0;
    const end = ta.selectionEnd ?? start;
    return end > start ? ta.value.slice(start, end).trim() : '';
  }

  const editor = document.getElementById('logbook-rich-content');
  const selection = window.getSelection?.();
  if (!editor || !selection || !selection.rangeCount || !editor.contains(target)) return '';
  const range = selection.getRangeAt(0);
  const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
  const endsInside = range.endContainer === editor || editor.contains(range.endContainer);
  return !range.collapsed && startsInside && endsInside ? selection.toString().trim() : '';
}

function _selectionMenuOutsideClick(event) {
  if (_selectionMenu?.contains(event.target)) return;
  _closeSelectionMenu();
}

function _selectionMenuKeydown(event) {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation?.();
  _closeSelectionMenu();
}

function _closeSelectionMenu() {
  if (_selectionMenu?.parentNode) _selectionMenu.remove();
  _selectionMenu = null;
  document.removeEventListener('mousedown', _selectionMenuOutsideClick, true);
  document.removeEventListener('keydown', _selectionMenuKeydown, true);
  window.removeEventListener('resize', _closeSelectionMenu, true);
  window.removeEventListener('scroll', _closeSelectionMenu, true);
}

function _entityKindName(kind) {
  return kind === 'location' ? 'place' : 'person';
}

function _entityKindPlural(kind) {
  return kind === 'location' ? 'places' : 'people';
}

function _entityChooserList(kind) {
  return kind === 'location'
    ? (_locations || []).filter(location => !location.hidden)
    : (_people || []);
}

function _entityChooserExact(kind, label, list) {
  return kind === 'location'
    ? _locationForLinkIn(list, '', label)
    : _personForLinkIn(list, '', label);
}

function _entityChooserMeta(item) {
  const aliases = (item?.aliases || []).slice(0, 3).join(', ');
  return _directoryMeta(item, aliases);
}

function _entityChooserChoiceHtml({ kind, target, title, meta = '', primary = false }) {
  return `
    <button type="button" class="logbook-entity-choice ${primary ? 'primary' : ''}" data-logbook-entity-target="${_e(target)}">
      <span class="logbook-entity-choice-icon">${_logbookIcon(kind === 'location' ? 'location' : 'person', 13)}</span>
      <span class="logbook-entity-choice-main">
        <strong>${_e(title)}</strong>
        ${meta ? `<span>${_e(meta)}</span>` : ''}
      </span>
    </button>
  `;
}

function _entityChooserRowsHtml(kind, label, query = '') {
  const list = _entityChooserList(kind);
  const exact = _entityChooserExact(kind, label, list);
  const matches = _entityAutocompleteMatches(list, query, { limit: 18 });
  const seenTargets = new Set();
  const rows = [];

  if (!exact) {
    rows.push(_entityChooserChoiceHtml({
      kind,
      target: _linkTargetForEntity(kind, null, label),
      title: `New ${_entityKindName(kind)}`,
      meta: label,
      primary: true,
    }));
  }

  [exact, ...matches].filter(Boolean).forEach(item => {
    const target = _linkTargetForEntity(kind, item, label);
    if (!target || seenTargets.has(target)) return;
    seenTargets.add(target);
    rows.push(_entityChooserChoiceHtml({
      kind,
      target,
      title: item.display_name || label,
      meta: _entityChooserMeta(item),
    }));
  });

  if (rows.length) return rows.join('');
  return `<div class="logbook-entity-empty">No matching ${_entityKindPlural(kind)}.</div>`;
}

function _entityChooserAnchorRect(snapshot) {
  if (snapshot?.getBoundingClientRect) {
    const rect = snapshot.getBoundingClientRect();
    if (rect.width || rect.height) return rect;
  }
  if (snapshot?.range?.getBoundingClientRect) {
    const rect = snapshot.range.getBoundingClientRect();
    if (rect.width || rect.height) return rect;
  }
  if (snapshot?.ta?.getBoundingClientRect) return snapshot.ta.getBoundingClientRect();
  return document.getElementById('logbook-rich-content')?.getBoundingClientRect?.()
    || document.getElementById('logbook-content')?.getBoundingClientRect?.()
    || null;
}

function _positionEntityLinkChooser(chooser, snapshot) {
  const anchor = _entityChooserAnchorRect(snapshot);
  const rect = chooser.getBoundingClientRect();
  const anchorLeft = anchor?.left ?? 16;
  const anchorTop = anchor?.top ?? 80;
  const anchorBottom = anchor?.bottom ?? anchorTop;
  let left = Math.max(8, Math.min(anchorLeft, window.innerWidth - rect.width - 8));
  let top = anchorBottom + 8;
  if (top + rect.height > window.innerHeight - 8 && anchorTop - rect.height - 8 > 8) {
    top = anchorTop - rect.height - 8;
  }
  top = Math.max(8, Math.min(top, window.innerHeight - rect.height - 8));
  chooser.style.left = `${left}px`;
  chooser.style.top = `${top}px`;
}

function _entityLinkChooserOutsideClick(event) {
  if (_entityLinkChooser?.contains(event.target)) return;
  _closeEntityLinkChooser();
}

function _entityLinkChooserKeydown(event) {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  _closeEntityLinkChooser();
}

function _closeEntityLinkChooser() {
  if (_entityLinkChooser?.parentNode) _entityLinkChooser.remove();
  _entityLinkChooser = null;
  document.removeEventListener('mousedown', _entityLinkChooserOutsideClick, true);
  document.removeEventListener('keydown', _entityLinkChooserKeydown, true);
  window.removeEventListener('resize', _closeEntityLinkChooser, true);
  window.removeEventListener('scroll', _closeEntityLinkChooser, true);
}

function _showEntityLinkChooser(kind, snapshot, options = {}) {
  const parts = options.label
    ? _selectionLinkParts(options.label)
    : _selectionLinkParts(snapshot?.text || '');
  if (!parts) return false;
  _closeSelectionMenu();
  _closeEntityLinkChooser();

  const name = _entityKindName(kind);
  const verb = options.verb || 'Link';
  const selectedLabel = options.selectedLabel || 'Selected';
  const anchor = options.anchor || snapshot;
  const onChoose = options.onChoose
    || (target => _replaceSelectionSnapshotWithLink(kind, snapshot, target));
  const chooser = document.createElement('div');
  chooser.className = 'logbook-entity-chooser';
  chooser.setAttribute('role', 'dialog');
  chooser.setAttribute('aria-label', `Choose ${name}`);
  chooser.innerHTML = `
    <div class="logbook-entity-chooser-head">
      <strong>${_logbookIcon(kind === 'location' ? 'location' : 'person', 14)} ${_e(verb)} ${_e(name)}</strong>
      <button type="button" class="logbook-icon-btn" data-logbook-entity-close aria-label="Close">x</button>
    </div>
    <div class="logbook-entity-selected"><span>${_e(selectedLabel)}</span><strong>${_e(parts.label)}</strong></div>
    <input class="memory-search-input logbook-entity-search" data-logbook-entity-search placeholder="Search ${_e(_entityKindPlural(kind))}">
    <div class="logbook-entity-choice-list" data-logbook-entity-list></div>
  `;
  const input = chooser.querySelector('[data-logbook-entity-search]');
  const list = chooser.querySelector('[data-logbook-entity-list]');
  const renderRows = () => {
    if (list) list.innerHTML = _entityChooserRowsHtml(kind, parts.label, input?.value || '');
    _positionEntityLinkChooser(chooser, anchor);
  };

  chooser.addEventListener('mousedown', event => {
    if (event.target.closest('[data-logbook-entity-target], [data-logbook-entity-close]')) {
      event.preventDefault();
    }
  });
  chooser.addEventListener('click', event => {
    const closeBtn = event.target.closest('[data-logbook-entity-close]');
    const choice = event.target.closest('[data-logbook-entity-target]');
    if (!closeBtn && !choice) return;
    event.preventDefault();
    event.stopPropagation();
    if (closeBtn) {
      _closeEntityLinkChooser();
      return;
    }
    const target = choice.dataset.logbookEntityTarget || '';
    _closeEntityLinkChooser();
    const linked = onChoose(target);
    if (!linked) _setStatus('Select text first');
  });
  input?.addEventListener('input', renderRows);

  document.body.appendChild(chooser);
  _entityLinkChooser = chooser;
  renderRows();
  setTimeout(() => {
    input?.focus();
    document.addEventListener('mousedown', _entityLinkChooserOutsideClick, true);
    document.addEventListener('keydown', _entityLinkChooserKeydown, true);
    window.addEventListener('resize', _closeEntityLinkChooser, true);
    window.addEventListener('scroll', _closeEntityLinkChooser, true);
  }, 0);
  return true;
}

function _selectionMenuItems({ tokenOnly = false } = {}) {
  if (tokenOnly) {
    return [[{ unlink: true, label: 'Unlink', icon: 'unlink' }]];
  }
  return [
    [
      { format: 'bold', label: 'Bold', icon: 'bold' },
      { format: 'italic', label: 'Italic', icon: 'italic' },
      { format: 'strike', label: 'Strike', icon: 'strike' },
      { format: 'link', label: 'Link', icon: 'link' },
    ],
    [
      { format: 'h1', label: 'Heading 1', textIcon: 'H1' },
      { format: 'h2', label: 'Heading 2', textIcon: 'H2' },
      { format: 'h3', label: 'Heading 3', textIcon: 'H3' },
      { format: 'quote', label: 'Quote', icon: 'quote' },
    ],
    [
      { format: 'ul', label: 'Bullets', icon: 'list' },
      { format: 'ol', label: 'Numbers', icon: 'orderedList' },
      { format: 'code', label: 'Code', icon: 'code' },
      { format: 'codeblock', label: 'Code block', icon: 'codeBlock' },
      { format: 'hr', label: 'Rule', icon: 'hr' },
    ],
    [
      { linkKind: 'person', label: 'Person', icon: 'person' },
      { linkKind: 'location', label: 'Place', icon: 'location' },
      { linkKind: 'food', label: 'Food', icon: 'food' },
      { unlink: true, label: 'Unlink', icon: 'unlink' },
    ],
  ];
}

function _selectionMenuButtonHtml(item) {
  const icon = item.textIcon
    ? `<span class="logbook-context-text-icon">${_e(item.textIcon)}</span>`
    : _logbookIcon(item.icon || 'person', 13);
  const attrs = item.format
    ? `data-logbook-context-format="${_e(item.format)}"`
    : item.linkKind
      ? `data-logbook-context-link="${_e(item.linkKind)}"`
      : 'data-logbook-context-unlink="1"';
  return `<button type="button" class="logbook-context-item" ${attrs}>${icon}<span>${_e(item.label)}</span></button>`;
}

function _showSelectionContextMenu(x, y, options = {}) {
  _closeSelectionMenu();
  _closeEntityLinkChooser();
  const menu = document.createElement('div');
  menu.className = 'logbook-selection-menu';
  menu.innerHTML = _selectionMenuItems(options)
    .map(group => `<div class="logbook-selection-menu-group">${group.map(_selectionMenuButtonHtml).join('')}</div>`)
    .join('');
  menu.addEventListener('mousedown', event => event.preventDefault());
  menu.addEventListener('click', event => {
    const formatBtn = event.target.closest('[data-logbook-context-format]');
    const linkBtn = event.target.closest('[data-logbook-context-link]');
    const unlinkBtn = event.target.closest('[data-logbook-context-unlink]');
    if (!formatBtn && !linkBtn && !unlinkBtn) return;
    event.preventDefault();
    event.stopPropagation();

    if (formatBtn) {
      const format = formatBtn.dataset.logbookContextFormat || '';
      const closeAfter = format === 'link';
      if (!closeAfter) _closeSelectionMenu();
      _formatSelectedText(format)
        .catch(_showError)
        .finally(() => {
          if (closeAfter) _closeSelectionMenu();
        });
      return;
    }

    _closeSelectionMenu();
    if (linkBtn) {
      _linkSelectedText(linkBtn.dataset.logbookContextLink || 'person');
      return;
    }
    _unlinkSelectedText();
  });
  document.body.appendChild(menu);
  _selectionMenu = menu;

  const rect = menu.getBoundingClientRect();
  const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
  const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;

  setTimeout(() => {
    document.addEventListener('mousedown', _selectionMenuOutsideClick, true);
    document.addEventListener('keydown', _selectionMenuKeydown, true);
    window.addEventListener('resize', _closeSelectionMenu, true);
    window.addEventListener('scroll', _closeSelectionMenu, true);
  }, 0);
}

function _openSelectionContextMenu(event) {
  if (_editorMode !== 'raw') {
    const token = event.target.closest?.('[data-logbook-token="1"]');
    if (_selectEditorToken(token, event)) {
      _showSelectionContextMenu(event.clientX, event.clientY, { tokenOnly: true });
      return;
    }
  }
  const selected = _selectedTextInsideLogbookEditor(event.target);
  if (!selected) {
    _closeSelectionMenu();
    return;
  }
  event.preventDefault();
  _showSelectionContextMenu(event.clientX, event.clientY);
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

function _bindAIEvents(root = document) {
  root.querySelectorAll('[data-ai-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.aiMode || 'structure_day';
      _selectAIMode(mode);
    });
  });
  root.querySelector('#logbook-run-ai')?.addEventListener('click', () => {
    if (_aiSelectedMode === 'extract_facts') _extractFacts().catch(_showError);
    else _runAI(_aiSelectedMode).catch(_showError);
  });
  root.querySelector('#logbook-extract-facts')?.addEventListener('click', () => _extractFacts().catch(_showError));
  root.querySelector('#logbook-apply-ai')?.addEventListener('click', () => _applyAIContent());
  root.querySelector('#logbook-copy-ai')?.addEventListener('click', () => _copyAI());
  root.querySelector('#logbook-clear-ai')?.addEventListener('click', () => {
    _aiPreview = null;
    _aiError = '';
    _renderAIAffectedPanels();
  });
  root.querySelector('#logbook-apply-ai-mood')?.addEventListener('click', () => _applyAIMood());
  root.querySelector('#logbook-add-ai-data')?.addEventListener('click', () => _addAIData());
  _bindAISuggestionEvents(root);
  _bindEntityLinkEvents(root);
}

function _bindAISuggestionEvents(root = document) {
  root.querySelectorAll('[data-add-ai-person]').forEach(btn => {
    btn.addEventListener('click', () => _addAIEntity('person', Number(btn.dataset.addAiPerson)).catch(_showError));
  });
  root.querySelectorAll('[data-add-ai-location]').forEach(btn => {
    btn.addEventListener('click', () => _addAIEntity('location', Number(btn.dataset.addAiLocation)).catch(_showError));
  });
}

function _cancelFloatingEntityCardHide() {
  if (!_floatingEntityCardHideTimer) return;
  clearTimeout(_floatingEntityCardHideTimer);
  _floatingEntityCardHideTimer = null;
}

function _closeFloatingEntityCard() {
  _cancelFloatingEntityCardHide();
  if (_floatingEntityCard?.parentNode) _floatingEntityCard.remove();
  _floatingEntityCard = null;
  _floatingEntityCardSource = null;
  window.removeEventListener('resize', _closeFloatingEntityCard, true);
  window.removeEventListener('scroll', _closeFloatingEntityCard, true);
}

function _scheduleFloatingEntityCardClose(delay = 140) {
  _cancelFloatingEntityCardHide();
  _floatingEntityCardHideTimer = setTimeout(_closeFloatingEntityCard, delay);
}

function _entityCardSource(source) {
  return source?.closest?.('[data-logbook-token="1"], .logbook-person-link') || null;
}

function _positionFloatingEntityCard(card, source) {
  if (!card || !source?.getBoundingClientRect) return;
  const sourceRect = source.getBoundingClientRect();
  const cardRect = card.getBoundingClientRect();
  const gap = 8;
  const width = cardRect.width || 280;
  const height = cardRect.height || 160;
  let left = sourceRect.left;
  let top = sourceRect.bottom + gap;
  if (top + height > window.innerHeight - gap && sourceRect.top - height - gap > gap) {
    top = sourceRect.top - height - gap;
  }
  left = Math.max(gap, Math.min(left, window.innerWidth - width - gap));
  top = Math.max(gap, Math.min(top, window.innerHeight - height - gap));
  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
}

function _editableFloatingEntityToken(sourceEl) {
  const editor = document.getElementById('logbook-rich-content');
  return sourceEl?.dataset?.logbookToken === '1' && editor?.contains(sourceEl) ? sourceEl : null;
}

function _floatingEntityCardActionsHtml(sourceEl) {
  const token = _editableFloatingEntityToken(sourceEl);
  const personId = sourceEl?.dataset?.openPerson || '';
  const locationId = sourceEl?.dataset?.openLocation || '';
  const kind = token ? _linkKind(token.dataset.target || '') : '';
  const actions = [];
  if (personId) {
    actions.push(`<button type="button" class="logbook-floating-card-btn" data-logbook-floating-open-person="${_e(personId)}">${_logbookIcon('person', 12)}<span>Open dashboard</span></button>`);
  } else if (locationId) {
    actions.push(`<button type="button" class="logbook-floating-card-btn" data-logbook-floating-open-location="${_e(locationId)}">${_logbookIcon('location', 12)}<span>Open place</span></button>`);
  }
  if (token && (kind === 'person' || kind === 'location')) {
    actions.push(`<button type="button" class="logbook-floating-card-btn" data-logbook-floating-change="${_e(kind)}">${_logbookIcon(kind === 'location' ? 'location' : 'person', 12)}<span>Change ${_e(_entityKindName(kind))}</span></button>`);
  }
  if (token) {
    actions.push(`<button type="button" class="logbook-floating-card-btn danger" data-logbook-floating-unlink>${_logbookIcon('unlink', 12)}<span>Unlink</span></button>`);
  }
  if (!actions.length) return '';
  return `
    <span class="logbook-floating-card-actions">
      ${actions.join('')}
    </span>
  `;
}

function _replaceEditorTokenTarget(token, target, { select = false } = {}) {
  const editor = document.getElementById('logbook-rich-content');
  if (!editor || !token || !target || token.dataset?.logbookToken !== '1' || !editor.contains(token)) return false;
  const label = token.dataset.label || String(token.textContent || '').trim();
  if (!label) return false;
  const template = document.createElement('template');
  template.innerHTML = _editorTokenHtml(label, target);
  const next = template.content.firstElementChild;
  if (!next) return false;
  if (_activeEditorToken === token) _clearActiveEditorToken();
  token.replaceWith(next);
  _bindEntityLinkEvents(editor);
  if (select) _selectEditorToken(next);
  const value = _syncEntryFromEditor();
  const raw = document.getElementById('logbook-content');
  if (raw && raw.value !== value) raw.value = value;
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _showEntityTokenChooser(kind, token) {
  if (kind !== 'person' && kind !== 'location') return false;
  const label = token?.dataset?.label || String(token?.textContent || '').trim();
  if (!label) return false;
  return _showEntityLinkChooser(kind, { text: label }, {
    anchor: token,
    label,
    verb: 'Change',
    selectedLabel: 'Current',
    onChoose: target => _replaceEditorTokenTarget(token, target),
  });
}

function _handleFloatingEntityCardAction(event) {
  if (event.type === 'pointerdown' && event.button !== 0) return false;
  const openPersonBtn = event.target.closest('[data-logbook-floating-open-person]');
  const openLocationBtn = event.target.closest('[data-logbook-floating-open-location]');
  const unlinkBtn = event.target.closest('[data-logbook-floating-unlink]');
  const changeBtn = event.target.closest('[data-logbook-floating-change]');
  if (!openPersonBtn && !openLocationBtn && !unlinkBtn && !changeBtn) return false;

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation?.();

  if (openPersonBtn) {
    const personId = openPersonBtn.dataset.logbookFloatingOpenPerson || '';
    _closeFloatingEntityCard();
    _openPerson(personId).catch(_showError);
    return true;
  }
  if (openLocationBtn) {
    const locationId = openLocationBtn.dataset.logbookFloatingOpenLocation || '';
    _closeFloatingEntityCard();
    _openLocation(locationId).catch(_showError);
    return true;
  }

  const token = _editableFloatingEntityToken(_floatingEntityCardSource);
  if (!token) return true;
  _setActiveEditorToken(token);
  _closeFloatingEntityCard();
  if (unlinkBtn) {
    _unlinkSelectedText();
    return true;
  }
  _showEntityTokenChooser(changeBtn.dataset.logbookFloatingChange || '', token);
  return true;
}

function _showFloatingEntityCard(source) {
  const sourceEl = _entityCardSource(source);
  const card = sourceEl?.querySelector?.('.logbook-person-card');
  if (!sourceEl || !card) return false;
  _cancelFloatingEntityCardHide();
  if (_floatingEntityCardSource === sourceEl && _floatingEntityCard) {
    _positionFloatingEntityCard(_floatingEntityCard, sourceEl);
    return true;
  }

  _closeFloatingEntityCard();
  const clone = card.cloneNode(true);
  clone.classList.add('logbook-floating-entity-card');
  clone.removeAttribute('style');
  clone.insertAdjacentHTML('beforeend', _floatingEntityCardActionsHtml(sourceEl));
  clone.addEventListener('mouseenter', _cancelFloatingEntityCardHide);
  clone.addEventListener('mouseleave', () => _scheduleFloatingEntityCardClose());
  clone.addEventListener('pointerdown', _handleFloatingEntityCardAction);
  clone.addEventListener('click', _handleFloatingEntityCardAction);
  document.body.appendChild(clone);
  _floatingEntityCard = clone;
  _floatingEntityCardSource = sourceEl;
  _positionFloatingEntityCard(clone, sourceEl);
  window.addEventListener('resize', _closeFloatingEntityCard, true);
  window.addEventListener('scroll', _closeFloatingEntityCard, true);
  return true;
}

function _bindFloatingEntityCards(root = document) {
  root.querySelectorAll('.logbook-person-link, [data-logbook-token="1"]').forEach(source => {
    if (source.dataset.boundFloatingEntityCard === '1') return;
    source.dataset.boundFloatingEntityCard = '1';
    source.addEventListener('mouseenter', () => _showFloatingEntityCard(source));
    source.addEventListener('mouseleave', () => _scheduleFloatingEntityCardClose());
    source.addEventListener('focus', () => _showFloatingEntityCard(source));
    source.addEventListener('blur', () => _scheduleFloatingEntityCardClose());
  });
}

function _clearActiveEditorToken() {
  if (_activeEditorToken?.classList) _activeEditorToken.classList.remove('is-selected');
  _activeEditorToken = null;
}

function _setActiveEditorToken(token, { focus = false } = {}) {
  const editor = document.getElementById('logbook-rich-content');
  if (!editor || !token || token.dataset?.logbookToken !== '1' || !editor.contains(token)) return false;
  if (_activeEditorToken && _activeEditorToken !== token) {
    _activeEditorToken.classList?.remove('is-selected');
  }
  _activeEditorToken = token;
  token.classList.add('is-selected');
  if (focus) token.focus?.();
  return true;
}

function _editorTokenFromEvent(event, editor = document.getElementById('logbook-rich-content')) {
  if (!editor || !event) return null;
  const direct = event.target?.closest?.('[data-logbook-token="1"]');
  if (direct && editor.contains(direct)) return direct;
  const pointed = document.elementFromPoint?.(event.clientX, event.clientY)
    ?.closest?.('[data-logbook-token="1"]');
  return pointed && editor.contains(pointed) ? pointed : null;
}

function _selectEditorToken(token, event = null) {
  if (!_setActiveEditorToken(token, { focus: true })) return false;
  _showFloatingEntityCard(token);
  event?.preventDefault?.();
  event?.stopPropagation?.();
  event?.stopImmediatePropagation?.();
  return true;
}

function _bindEditorTokenSelection(root = document) {
  const editor = root.id === 'logbook-rich-content'
    ? root
    : root.querySelector?.('#logbook-rich-content');
  if (!editor) return;
  editor.querySelectorAll('[data-logbook-token="1"]').forEach(token => {
    if (token.dataset.boundEditorToken === '1') return;
    token.dataset.boundEditorToken = '1';
    token.addEventListener('pointerdown', event => {
      if (event.button === 0) _selectEditorToken(token, event);
    });
    token.addEventListener('mousedown', event => {
      if (event.button === 0) _selectEditorToken(token, event);
    });
    token.addEventListener('click', event => _selectEditorToken(token, event));
    token.addEventListener('focus', () => _selectEditorToken(token));
    token.addEventListener('contextmenu', event => {
      if (!_selectEditorToken(token, event)) return;
      _showSelectionContextMenu(event.clientX, event.clientY, { tokenOnly: true });
    });
  });
}

function _bindEntityLinkEvents(root = document) {
  _bindEditorTokenSelection(root);
  _bindFloatingEntityCards(root);
  root.querySelectorAll('[data-open-person]').forEach(link => {
    if (link.dataset.boundPersonLink === '1') return;
    link.dataset.boundPersonLink = '1';
    link.addEventListener('click', async event => {
      if (_selectEditorToken(link, event)) return;
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
      if (_selectEditorToken(link, event)) return;
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
  _bindDirectoryRowActions(document, {
    onInsertPerson: _insertMention,
    onFilterPerson: personId => {
      _filterPerson = personId;
      _loadEntries().then(_renderNavigator).catch(_showError);
    },
  });
}

function _bindLocationRowEvents() {
  _bindDirectoryRowActions(document, {
    onInsertLocation: _insertLocation,
    onFilterLocation: locationId => {
      _filterLocation = locationId;
      _loadEntries().then(_renderNavigator).catch(_showError);
    },
  });
}

function _bindPeopleDirectoryEvents() {
  _bindDirectoryControls({
    searchId: 'logbook-people-search',
    sortId: 'logbook-people-sort',
    listId: 'logbook-people-list',
    onSearch: value => { _peopleSearch = value; },
    onSort: value => { _peopleSort = value; },
    renderRows: _peopleRowsHtml,
    bindRows: _bindPeopleRowEvents,
  });
}

function _bindLocationDirectoryEvents() {
  _bindDirectoryControls({
    searchId: 'logbook-location-search',
    sortId: 'logbook-location-sort',
    listId: 'logbook-location-list',
    onSearch: value => { _locationSearch = value; },
    onSort: value => { _locationSort = value; },
    renderRows: _locationRowsHtml,
    bindRows: _bindLocationRowEvents,
    createId: 'logbook-create-location',
    onCreate: () => _createLocation().catch(_showError),
  });
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

function _renderAIPanel() {
  const panel = document.querySelector('.logbook-panel[data-mobile-section="ai"]');
  if (!panel) return;
  panel.innerHTML = _aiHtml();
  _bindAIEvents(panel);
}

function _renderAIAffectedPanels() {
  _renderAIPanel();
  _renderPeoplePanel();
  _renderLocationsPanel();
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

function _rawAutocompleteContext() {
  if (_editorMode !== 'raw') return null;
  const ta = document.getElementById('logbook-content');
  if (!ta) return null;
  const context = _entityAutocompleteContext(ta.value, ta.selectionStart ?? 0);
  return context ? { ...context, textarea: ta } : null;
}

function _renderMentionMenu() {
  const menu = document.getElementById('logbook-mention-menu');
  const ctx = _rawAutocompleteContext();
  if (!menu || !ctx) {
    _hideMentionMenu();
    return;
  }
  const isPerson = ctx.kind === 'person';
  const matches = _entityAutocompleteMatches(isPerson ? _people : _locations, ctx.query);
  if (!matches.length) {
    _hideMentionMenu();
    return;
  }
  menu.classList.remove('hidden');
  menu.innerHTML = isPerson
    ? matches.map(p => `<button type="button" data-mention-person="${_e(p.display_name)}">${_logbookIcon('person', 12)}<span>${_e(p.display_name)}</span></button>`).join('')
    : matches.map(loc => `<button type="button" data-mention-location="${_e(loc.display_name)}">${_logbookIcon('location', 12)}<span>${_e(loc.display_name)}</span></button>`).join('');
  menu.querySelectorAll('[data-mention-person], [data-mention-location]').forEach(btn => {
    btn.addEventListener('mousedown', e => {
      e.preventDefault();
      if (btn.dataset.mentionPerson) _replaceMention(ctx, btn.dataset.mentionPerson);
      else _replaceLocation(ctx, btn.dataset.mentionLocation);
    });
  });
}

function _hideMentionMenu() {
  const menu = document.getElementById('logbook-mention-menu');
  if (menu) menu.classList.add('hidden');
}

function _mentionText(name) {
  return _mentionMarkdown(name, _people);
}

function _locationText(name) {
  return _locationMarkdown(name, _locations);
}

function _selectionLinkTarget(kind, label) {
  return _selectionLinkTargetForLists(kind, label, { people: _people, locations: _locations });
}

function _updateRawContentValue(ta, value, selectionStart = null, selectionEnd = null) {
  ta.value = value;
  ta.focus();
  if (selectionStart !== null && selectionEnd !== null) ta.setSelectionRange(selectionStart, selectionEnd);
  if (_entry) _entry.content = ta.value;
  _refreshTokenEstimate(ta.value);
  _refreshEntityPanelsFromContent();
  _markDirty();
}

function _replaceRawRange(start, end, replacement, selectStart = null, selectEnd = null) {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  const next = ta.value.slice(0, start) + replacement + ta.value.slice(end);
  const cursor = start + replacement.length;
  _updateRawContentValue(
    ta,
    next,
    selectStart === null ? cursor : selectStart,
    selectEnd === null ? cursor : selectEnd,
  );
  return true;
}

function _toggleRawSelectionFormat(prefix, suffix, placeholder = 'text', options = {}) {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  const edit = _toggleMarkdownSelectionFormat(
    ta.value,
    ta.selectionStart ?? 0,
    ta.selectionEnd ?? ta.selectionStart ?? 0,
    prefix,
    suffix,
    placeholder,
    options,
  );
  if (!edit) return false;
  return _replaceRawRange(edit.start, edit.end, edit.text, edit.selectionStart, edit.selectionEnd);
}

function _applyRawMarkdownEdit(edit) {
  if (!edit) return false;
  return _replaceRawRange(edit.start, edit.end, edit.text, edit.selectionStart, edit.selectionEnd);
}

function _toggleRawHeading(prefix) {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  return _applyRawMarkdownEdit(_toggleMarkdownHeading(ta.value, ta.selectionStart ?? 0, prefix));
}

function _toggleRawLinePrefix(prefix) {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  return _applyRawMarkdownEdit(_toggleMarkdownLinePrefix(
    ta.value,
    ta.selectionStart ?? 0,
    ta.selectionEnd ?? ta.selectionStart ?? 0,
    prefix,
  ));
}

function _toggleRawOrderedList() {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  return _applyRawMarkdownEdit(_toggleMarkdownOrderedList(
    ta.value,
    ta.selectionStart ?? 0,
    ta.selectionEnd ?? ta.selectionStart ?? 0,
  ));
}

function _toggleRawCodeBlock() {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  return _applyRawMarkdownEdit(_toggleMarkdownCodeBlock(
    ta.value,
    ta.selectionStart ?? 0,
    ta.selectionEnd ?? ta.selectionStart ?? 0,
  ));
}

function _insertRawHorizontalRule() {
  const ta = document.getElementById('logbook-content');
  if (!ta) return false;
  return _applyRawMarkdownEdit(_insertMarkdownHorizontalRule(
    ta.value,
    ta.selectionStart ?? 0,
    ta.selectionEnd ?? ta.selectionStart ?? 0,
  ));
}

function _rawSelectionSnapshot() {
  const ta = document.getElementById('logbook-content');
  if (!ta) return null;
  const start = ta.selectionStart ?? 0;
  const end = ta.selectionEnd ?? start;
  const text = ta.value.slice(start, end);
  return { mode: 'raw', ta, start, end, text };
}

function _richSelectionSnapshot() {
  const editor = document.getElementById('logbook-rich-content');
  const selection = window.getSelection?.();
  if (!editor || !selection || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  const startsInside = range.startContainer === editor || editor.contains(range.startContainer);
  const endsInside = range.endContainer === editor || editor.contains(range.endContainer);
  const text = selection.toString();
  if (range.collapsed || !startsInside || !endsInside || !text.trim()) return null;
  return { mode: 'rich', editor, range: range.cloneRange(), text };
}

function _restoreRichSelection(snapshot) {
  if (!snapshot?.editor || !snapshot.range) return false;
  const selection = window.getSelection?.();
  if (!selection) return false;
  selection.removeAllRanges();
  selection.addRange(snapshot.range);
  snapshot.editor.focus();
  return true;
}

async function _promptMarkdownUrl() {
  const value = await uiModule.styledPrompt('URL', {
    title: 'Link',
    placeholder: 'https://example.com',
    confirmText: 'Apply',
    maxLength: 700,
  });
  return _normalizeMarkdownUrl(value);
}

function _labelForMarkdownLink(value) {
  return String(value || '')
    .replace(/[\r\n]+/g, ' ')
    .replace(/\\/g, '\\\\')
    .replace(/\]/g, '\\]')
    .trim();
}

function _rawLinkSelection(snapshot, url) {
  if (!snapshot?.ta || !snapshot.text.trim() || !_safeMarkdownHref(url)) return false;
  const label = _labelForMarkdownLink(snapshot.text);
  const replacement = `[${label}](${_normalizeMarkdownUrl(url).replace(/\)/g, '%29')})`;
  return _replaceRawRange(snapshot.start, snapshot.end, replacement);
}

function _wrapRichSelectionWithTag(tagName, attrs = {}, snapshot = null) {
  const editor = document.getElementById('logbook-rich-content');
  if (snapshot && !_restoreRichSelection(snapshot)) return false;
  const wrapped = _wrapRichSelection(editor, tagName, { attrs });
  if (!wrapped) return false;
  _syncEntryFromEditor();
  _bindEntityLinkEvents(editor);
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _applyRichEditorCommand(command) {
  const editor = document.getElementById('logbook-rich-content');
  if (!editor || _editorMode === 'raw') return false;
  editor.focus();
  let applied = false;
  try {
    applied = document.execCommand(command);
  } catch (_) {
    applied = false;
  }
  _syncEntryFromEditor();
  _bindEntityLinkEvents(editor);
  _refreshEntityPanelsFromContent();
  _markDirty();
  return applied;
}

function _currentRichBlockTag(editor) {
  const selection = window.getSelection?.();
  if (!editor || !selection || !selection.rangeCount) return '';
  let node = selection.getRangeAt(0).startContainer;
  if (node?.nodeType === 3) node = node.parentNode;
  while (node && node !== editor) {
    const tag = String(node.tagName || '').toLowerCase();
    if (/^(h1|h2|h3|h4|h5|h6|p|div|pre|blockquote|li)$/.test(tag)) return tag;
    node = node.parentNode;
  }
  return '';
}

function _applyRichBlockCommand(format) {
  const editor = document.getElementById('logbook-rich-content');
  if (!editor || _editorMode === 'raw') return false;
  editor.focus();
  const current = _currentRichBlockTag(editor);
  let command = '';
  let value = null;
  if (format === 'h1' || format === 'h2' || format === 'h3') {
    command = 'formatBlock';
    value = current === format ? 'div' : format;
  } else if (format === 'quote') {
    command = 'formatBlock';
    value = current === 'blockquote' ? 'div' : 'blockquote';
  } else if (format === 'codeblock') {
    command = 'formatBlock';
    value = current === 'pre' ? 'div' : 'pre';
  } else if (format === 'ul') {
    command = 'insertUnorderedList';
  } else if (format === 'ol') {
    command = 'insertOrderedList';
  } else if (format === 'hr') {
    command = 'insertHorizontalRule';
  }
  if (!command) return false;
  let applied = false;
  try {
    applied = value === null
      ? document.execCommand(command)
      : document.execCommand(command, false, value);
  } catch (_) {
    applied = false;
  }
  _syncEntryFromEditor();
  _bindEntityLinkEvents(editor);
  _refreshEntityPanelsFromContent();
  _markDirty();
  return applied;
}

function _applyRichInlineCode() {
  const wrapped = _wrapRichSelectionWithTag('code');
  if (!wrapped) _setStatus('Select text first');
  return wrapped;
}

async function _formatSelectedText(format) {
  if (format === 'bold') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawSelectionFormat('**', '**', 'bold')
      : _applyRichEditorCommand('bold');
    if (!formatted) _setStatus('Select text first');
    return;
  }
  if (format === 'italic') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawSelectionFormat('_', '_', 'italic', { aliases: [['*', '*']] })
      : _applyRichEditorCommand('italic');
    if (!formatted) _setStatus('Select text first');
    return;
  }
  if (format === 'strike') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawSelectionFormat('~~', '~~', 'strike')
      : _applyRichEditorCommand('strikeThrough');
    if (!formatted) _setStatus('Select text first');
    return;
  }
  if (format === 'h1' || format === 'h2' || format === 'h3') {
    const levels = { h1: '# ', h2: '## ', h3: '### ' };
    const formatted = _editorMode === 'raw'
      ? _toggleRawHeading(levels[format])
      : _applyRichBlockCommand(format);
    if (!formatted) _setStatus('Place the cursor in a line first');
    return;
  }
  if (format === 'quote') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawLinePrefix('> ')
      : _applyRichBlockCommand(format);
    if (!formatted) _setStatus('Place the cursor in a line first');
    return;
  }
  if (format === 'ul') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawLinePrefix('- ')
      : _applyRichBlockCommand(format);
    if (!formatted) _setStatus('Place the cursor in a line first');
    return;
  }
  if (format === 'ol') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawOrderedList()
      : _applyRichBlockCommand(format);
    if (!formatted) _setStatus('Place the cursor in a line first');
    return;
  }
  if (format === 'code') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawSelectionFormat('`', '`', 'code')
      : _applyRichInlineCode();
    if (!formatted) _setStatus('Select text first');
    return;
  }
  if (format === 'codeblock') {
    const formatted = _editorMode === 'raw'
      ? _toggleRawCodeBlock()
      : _applyRichBlockCommand(format);
    if (!formatted) _setStatus('Place the cursor in a line first');
    return;
  }
  if (format === 'hr') {
    const formatted = _editorMode === 'raw'
      ? _insertRawHorizontalRule()
      : _applyRichBlockCommand(format);
    if (!formatted) _setStatus('Place the cursor first');
    return;
  }
  if (format !== 'link') return;

  const snapshot = _editorMode === 'raw' ? _rawSelectionSnapshot() : _richSelectionSnapshot();
  if (!snapshot?.text?.trim()) {
    _setStatus('Select text first');
    return;
  }
  const url = await _promptMarkdownUrl();
  if (!url) return;
  if (!_safeMarkdownHref(url)) {
    _setStatus('Enter an http, https, mailto, or anchor link');
    return;
  }
  const linked = _editorMode === 'raw'
    ? _rawLinkSelection(snapshot, url)
    : _wrapRichSelectionWithTag('a', {
      href: _safeMarkdownHref(url),
      'data-logbook-markdown-link': '1',
      'data-href': _normalizeMarkdownUrl(url),
      target: '_blank',
      rel: 'noopener noreferrer',
      class: 'logbook-editor-link',
    }, snapshot);
  if (!linked) _setStatus('Select text first');
}

function _replaceRawSelectionWithLink(kind, snapshot = _rawSelectionSnapshot(), target = '') {
  if (!snapshot?.text?.trim()) return false;
  const linked = _linkedSelectionText(
    snapshot.text,
    kind,
    target ? () => target : _selectionLinkTarget,
  );
  if (!linked) return false;
  return _replaceRawRange(snapshot.start, snapshot.end, linked.markdown);
}

function _replaceRichSelectionWithLink(kind, snapshot = null, target = '') {
  const editor = document.getElementById('logbook-rich-content');
  if (snapshot && !_restoreRichSelection(snapshot)) return false;
  const linked = _replaceRichSelectionWithLinkIn(editor, kind, {
    resolveTarget: target ? () => target : _selectionLinkTarget,
    renderToken: _editorTokenHtml,
    escapeHtml: _e,
  });
  if (!linked) return false;
  _syncEntryFromEditor();
  _bindEntityLinkEvents(editor);
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _replaceSelectionSnapshotWithLink(kind, snapshot, target = '') {
  if (snapshot?.mode === 'raw') return _replaceRawSelectionWithLink(kind, snapshot, target);
  if (snapshot?.mode === 'rich') return _replaceRichSelectionWithLink(kind, snapshot, target);
  return false;
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
  const unlinked = _unlinkMarkdownSelection(ta.value || '', start, end);
  if (!unlinked) return false;
  return _replaceRawSelectionWithText(unlinked.start, unlinked.end, unlinked.text);
}

function _unlinkRichSelection() {
  const editor = document.getElementById('logbook-rich-content');
  const activeElement = _activeEditorToken && editor?.contains(_activeEditorToken)
    ? _activeEditorToken
    : document.activeElement;
  const unlinked = _unlinkRichSelectionIn(editor, { activeElement });
  if (!unlinked) return false;
  _clearActiveEditorToken();
  _syncEntryFromEditor();
  _refreshEntityPanelsFromContent();
  _markDirty();
  return true;
}

function _escapeActiveRichToken({ side = 'after', ensureSpace = true } = {}) {
  const editor = document.getElementById('logbook-rich-content');
  if (!editor || _editorMode === 'raw') return false;
  const token = _activeEditorToken && editor.contains(_activeEditorToken) ? _activeEditorToken : null;
  const escaped = _escapeRichEditorTokenIn(editor, {
    token,
    side,
    ensureSpace,
    activeElement: token || document.activeElement,
  });
  if (!escaped) return false;
  _clearActiveEditorToken();
  _closeFloatingEntityCard();
  if (escaped.changed) {
    _syncEntryFromEditor();
    _refreshEntityPanelsFromContent();
    _markDirty();
  }
  return true;
}

function _linkSelectedText(kind) {
  const snapshot = _editorMode === 'raw' ? _rawSelectionSnapshot() : _richSelectionSnapshot();
  if (!snapshot?.text?.trim()) {
    _setStatus('Select text first');
    return;
  }
  if (kind === 'person' || kind === 'location') {
    if (!_showEntityLinkChooser(kind, snapshot)) _setStatus('Select text first');
    return;
  }
  const linked = _replaceSelectionSnapshotWithLink(kind, snapshot);
  if (!linked) _setStatus('Select text first');
}

function _unlinkSelectedText() {
  const unlinked = _editorMode === 'raw'
    ? _unlinkRawSelection()
    : _unlinkRichSelection();
  if (!unlinked) _setStatus('Select a linked token first');
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

function _selectAIMode(mode) {
  const nextMode = mode || 'structure_day';
  if (_aiSelectedMode === nextMode) {
    _renderAIPanel();
    return;
  }
  _aiSelectedMode = nextMode;
  _aiError = '';
  _renderAIPanel();
  _loadAIEstimate(_aiSelectedMode, { render: true }).catch(() => {});
}

async function _runAI(mode) {
  _aiSelectedMode = mode || 'structure_day';
  if (_aiStatus?.available !== true) {
    _aiError = _aiStatus?.reason || 'No LLM provider configured.';
    _renderAIPanel();
    return;
  }
  if (_aiBusy) return;
  _aiBusy = true;
  _aiError = '';
  _aiPreview = null;
  _syncEntryFromEditor();
  _renderAIAffectedPanels();
  const content = _entry?.content || '';
  try {
    const result = await assistLogbook({
      entry_date: _date,
      content,
      mode: _aiSelectedMode,
      locale: _aiLocale(),
      current_entry: _entry || {},
    });
    _aiPreview = result;
    if (result?.usage?.estimate) {
      _aiEstimate = {
        ok: true,
        available: true,
        mode: _aiSelectedMode,
        model: result.usage.model,
        source: result.usage.source,
        billing: result.usage.billing,
        estimate: result.usage.estimate,
        day: result.usage.day,
        month: result.usage.month,
      };
    }
    if (result?.usage) {
      _aiUsageSummary = {
        ok: true,
        billing: result.usage.billing,
        day: result.usage.day,
        month: result.usage.month,
      };
    }
    await _loadAIUsageSummary();
  } catch (err) {
    _aiError = err.message || 'AI help failed. Your entry was not changed.';
  } finally {
    _aiBusy = false;
    _renderAIAffectedPanels();
  }
}

async function _extractFacts() {
  _aiSelectedMode = 'extract_facts';
  if (_aiStatus?.available !== true) {
    _aiError = _aiStatus?.reason || 'No LLM provider configured.';
    _renderAIPanel();
    return;
  }
  if (!_entry?.id || _dirty) {
    await _saveNow({ silent: true });
  }
  if (!_entry?.id) return;
  _aiBusy = true;
  _aiError = '';
  _renderAIPanel();
  try {
    const result = await analyzeEntry(_entry.id);
    _aiPreview = result;
    if (result?.usage) {
      _aiEstimate = {
        ok: true,
        available: true,
        mode: 'extract_facts',
        model: result.usage.model,
        source: result.usage.source,
        billing: result.usage.billing,
        estimate: result.usage.estimate,
        day: result.usage.day,
        month: result.usage.month,
      };
      _aiUsageSummary = {
        ok: true,
        billing: result.usage.billing,
        day: result.usage.day,
        month: result.usage.month,
      };
    }
    await Promise.all([_loadPeople(), _loadConnections(), _loadEntries()]);
    await _loadAIUsageSummary();
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
  _closeSelectionMenu();
  _closeEntityLinkChooser();
  _closeFloatingEntityCard();
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
