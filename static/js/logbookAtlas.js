/**
 * Daily Logbook people and places atlas.
 */

import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { applyEdgeDock } from './modalSnap.js';
import { mapSearchUrl, pointsWithCoordinates, pointsWithoutCoordinates, renderCoordinateMap } from './maps.js';
import {
  createConnection,
  createLocation,
  createPerson,
  createPersonFact,
  deleteLocation,
  getAtlas,
  getMapConfig,
  getPerson,
  getLocation,
  geocodeAddress,
  hideLocation,
  listContactCandidates,
  linkPersonContact,
  mergePeople,
  saveConnection,
  unlinkPersonContact,
  unhideLocation,
  updateConnection,
  updateLocation,
  updatePerson,
} from './logbook/api.js';
import { logbookIcon as _logbookIcon } from './logbook/icons.js';
import { escapeHtml as _e } from './logbook/utils.js';

const MODAL_ID = 'logbook-atlas-modal';
const CONNECTION_TYPES = ['friend', 'family', 'work', 'training', 'co_mentioned', 'conflict', 'unknown'];
const CONNECTION_STATUSES = ['accepted', 'suggested', 'hidden'];
const PERSON_RELATION_TYPES = ['family', 'partner', 'friend', 'colleague', 'work', 'training', 'neighbor', 'acquaintance', 'care', 'service', 'unknown'];
const PERSON_FACT_TYPES = ['workplace', 'relationship', 'role', 'location', 'preference', 'note', 'unknown'];

let _open = false;
let _tab = 'people';
let _atlas = { people: [], locations: [], connections: [], contacts_available: false };
let _selectedPersonId = '';
let _selectedLocationId = '';
let _personDetail = null;
let _locationDetail = null;
let _creatingPerson = false;
let _creatingLocation = false;
let _peopleSearch = '';
let _locationSearch = '';
let _locationTypeFilter = '';
let _contactQuery = '';
let _contactCandidates = [];
let _busy = false;
let _error = '';
let _windowRect = null;
let _editingConnectionId = '';
let _connectionDraft = null;
let _showConnectionForm = false;
let _locationGeocodeResults = [];
let _locationGeocodeQuery = '';
let _mapConfig = { tiles_enabled: false, provider: 'local', tile_url: '', attribution: '', max_zoom: 18 };
let _mapZoomOffset = 0;

function _iconAtlas(size = 16) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="3"/><path d="M2 21v-2a4 4 0 0 1 4-4h4"/><path d="M15 5l6 3-6 3-6-3 6-3z"/><path d="M9 8v8l6 3 6-3V8"/></svg>`;
}

function _setError(err) {
  _error = err?.message || err || '';
  if (_error) uiModule?.showError?.(_error);
}

function _visiblePeople() {
  const term = _peopleSearch.trim().toLowerCase();
  return (_atlas.people || [])
    .filter(person => {
      if (!term) return true;
      const names = [person.display_name, ...(person.aliases || []), person.relationship_label || '', person.notes || '', person.llm_context || '']
        .map(value => String(value || '').toLowerCase());
      return names.some(name => name.includes(term));
    })
    .sort((a, b) => (
      String(b.last_mentioned || '').localeCompare(String(a.last_mentioned || '')) ||
      Number(b.mention_count || 0) - Number(a.mention_count || 0) ||
      String(a.display_name || '').localeCompare(String(b.display_name || ''))
    ));
}

function _visibleLocations() {
  const term = _locationSearch.trim().toLowerCase();
  const type = _locationTypeFilter.trim().toLowerCase();
  return (_atlas.locations || [])
    .filter(location => {
      const names = [location.display_name, location.address || '', ...(location.aliases || []), location.location_type || '']
        .map(value => String(value || '').toLowerCase());
      return (!term || names.some(name => name.includes(term))) &&
        (!type || String(location.location_type || '').toLowerCase() === type);
    })
    .sort((a, b) => (
      String(b.last_mentioned || '').localeCompare(String(a.last_mentioned || '')) ||
      Number(b.mention_count || 0) - Number(a.mention_count || 0) ||
      String(a.display_name || '').localeCompare(String(b.display_name || ''))
    ));
}

function _locationTypes() {
  const out = [];
  for (const location of _atlas.locations || []) {
    const type = String(location.location_type || '').trim();
    if (type && !out.includes(type)) out.push(type);
  }
  return out.sort((a, b) => a.localeCompare(b));
}

function _hasLocationPin(location) {
  return location?.latitude !== null && location?.latitude !== undefined && location?.latitude !== '' &&
    location?.longitude !== null && location?.longitude !== undefined && location?.longitude !== '' &&
    Number.isFinite(Number(location.latitude)) && Number.isFinite(Number(location.longitude));
}

function _locationSearchText(location) {
  return [location?.address, location?.display_name]
    .map(value => String(value || '').trim())
    .filter(Boolean)
    .join(' ');
}

function _locationMapSearchLink(location) {
  const url = mapSearchUrl(_locationSearchText(location));
  if (!url) return '';
  return `<a class="cal-btn" href="${_e(url)}" target="_blank" rel="noopener noreferrer">Open map</a>`;
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

function _factTypeLabel(type) {
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
  return labels[value] || value.replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
}

function _personRelationOptionsHtml() {
  return `
    <datalist id="atlas-person-relation-types">
      ${PERSON_RELATION_TYPES.map(type => `<option value="${_e(type)}">${_e(_connectionTypeLabel(type))}</option>`).join('')}
    </datalist>
  `;
}

function _personFactTypeOptionsHtml(selected = 'note') {
  return PERSON_FACT_TYPES.map(type => (
    `<option value="${_e(type)}" ${selected === type ? 'selected' : ''}>${_e(_factTypeLabel(type))}</option>`
  )).join('');
}

function _connectionPersonChip(person, fallback) {
  const name = person?.display_name || fallback || 'Person';
  const attrs = person?.id ? ` type="button" data-connection-person="${_e(person.id)}"` : '';
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
  const editButton = `<button type="button" class="cal-btn" data-edit-connection="${_e(conn.id)}">Edit</button>`;
  const actions = status === 'suggested'
    ? `${editButton}<button type="button" class="cal-btn cal-btn-primary" data-accept-connection="${_e(conn.id)}">Accept</button><button type="button" class="cal-btn" data-hide-connection="${_e(conn.id)}">Hide</button>`
    : editButton;
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
      <div class="logbook-connection-actions">${actions}</div>
    </div>
  `;
}

function _connectionById(connectionId) {
  return (_atlas.connections || []).find(conn => conn.id === connectionId) || null;
}

function _defaultConnectionDraft() {
  const people = _atlas.people || [];
  const first = _selectedPersonId || people[0]?.id || '';
  const second = people.find(person => person.id !== first)?.id || '';
  return {
    person_a_id: first,
    person_b_id: second,
    connection_type: 'friend',
    status: 'accepted',
    strength: 2,
    confidence: 80,
    description: '',
  };
}

function _draftFromConnection(conn) {
  return {
    person_a_id: conn?.person_a_id || '',
    person_b_id: conn?.person_b_id || '',
    connection_type: conn?.connection_type || 'unknown',
    status: conn?.status || 'accepted',
    strength: conn?.strength || 1,
    confidence: conn?.confidence ?? 80,
    description: conn?.description || '',
  };
}

function _personSelectOptions(selectedId, excludeId = '') {
  return (_atlas.people || []).map(person => {
    const disabled = excludeId && person.id === excludeId ? ' disabled' : '';
    const selected = person.id === selectedId ? ' selected' : '';
    return `<option value="${_e(person.id)}"${selected}${disabled}>${_e(person.display_name || 'Person')}</option>`;
  }).join('');
}

function _connectionFormHtml() {
  const people = _atlas.people || [];
  if (people.length < 2) {
    return '<div class="logbook-empty">Add at least two people before creating a connection.</div>';
  }
  const editing = Boolean(_editingConnectionId);
  const draft = _connectionDraft || _defaultConnectionDraft();
  const typeOptions = CONNECTION_TYPES.map(type => (
    `<option value="${_e(type)}" ${draft.connection_type === type ? 'selected' : ''}>${_e(_connectionTypeLabel(type))}</option>`
  )).join('');
  const statusOptions = CONNECTION_STATUSES.map(status => (
    `<option value="${_e(status)}" ${draft.status === status ? 'selected' : ''}>${_e(status[0].toUpperCase() + status.slice(1))}</option>`
  )).join('');
  const locked = editing ? ' disabled' : '';
  return `
    <div class="logbook-connection-form">
      <div class="logbook-section-head">
        <h5>${editing ? 'Edit connection' : 'New connection'}</h5>
        <div class="logbook-atlas-actions">
          <button type="button" class="cal-btn cal-btn-primary" id="atlas-save-connection">${editing ? 'Save' : 'Create'}</button>
          <button type="button" class="cal-btn" id="atlas-cancel-connection">Cancel</button>
        </div>
      </div>
      <div class="logbook-connection-form-grid">
        <label>Person A<select id="atlas-connection-person-a" class="logbook-select"${locked}>${_personSelectOptions(draft.person_a_id, draft.person_b_id)}</select></label>
        <label>Person B<select id="atlas-connection-person-b" class="logbook-select"${locked}>${_personSelectOptions(draft.person_b_id, draft.person_a_id)}</select></label>
        <label>Type<select id="atlas-connection-type" class="logbook-select">${typeOptions}</select></label>
        <label>Status<select id="atlas-connection-status" class="logbook-select">${statusOptions}</select></label>
        <label>Strength<input id="atlas-connection-strength" class="memory-search-input" type="number" min="1" max="5" step="1" value="${_e(draft.strength || 1)}"></label>
        <label>Confidence<input id="atlas-connection-confidence" class="memory-search-input" type="number" min="0" max="100" step="1" value="${_e(draft.confidence ?? 80)}"></label>
      </div>
      <label>Description<textarea id="atlas-connection-description" class="logbook-atlas-text" placeholder="Why these people are connected">${_e(draft.description || '')}</textarea></label>
    </div>
  `;
}

async function _loadAtlas() {
  const [atlas, mapConfig] = await Promise.all([
    getAtlas(),
    getMapConfig().catch(err => ({
      tiles_enabled: false,
      provider: 'local',
      tile_url: '',
      attribution: '',
      max_zoom: 18,
      error: err?.message || 'Map tiles are unavailable',
    })),
  ]);
  _atlas = atlas;
  _mapConfig = mapConfig || { tiles_enabled: false, provider: 'local', tile_url: '', attribution: '', max_zoom: 18 };
  if (!_selectedPersonId && _atlas.people?.length) _selectedPersonId = _atlas.people[0].id;
  if (!_selectedLocationId && _atlas.locations?.length) _selectedLocationId = _atlas.locations[0].id;
}

async function _selectPerson(personId) {
  _creatingPerson = false;
  _selectedPersonId = personId;
  _personDetail = personId ? await getPerson(personId, new URLSearchParams({ limit: '30' })) : null;
  _contactCandidates = [];
  _contactQuery = '';
  _render();
}

async function _selectLocation(locationId) {
  _creatingLocation = false;
  _selectedLocationId = locationId;
  _locationGeocodeResults = [];
  _locationGeocodeQuery = '';
  _locationDetail = locationId ? await getLocation(locationId, new URLSearchParams({ limit: '30' })) : null;
  _render();
}

function _newPerson() {
  _creatingPerson = true;
  _selectedPersonId = '';
  _personDetail = null;
  _contactCandidates = [];
  _contactQuery = '';
  _render();
}

function _newLocation() {
  _creatingLocation = true;
  _selectedLocationId = '';
  _locationDetail = null;
  _locationGeocodeResults = [];
  _locationGeocodeQuery = '';
  _render();
}

function _captureWindowRect(modal) {
  if (!modal || window.innerWidth <= 900) return;
  if (modal.classList.contains('modal-left-docked') || modal.classList.contains('modal-right-docked')) return;
  const content = modal.querySelector('.logbook-atlas-content');
  if (!content) return;
  const rect = content.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  _windowRect = { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

function _restoreWindowRect(modal) {
  if (!modal || window.innerWidth <= 900) return;
  const content = modal.querySelector('.logbook-atlas-content');
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
  Object.assign(content.style, {
    position: 'fixed',
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    height: `${height}px`,
    maxHeight: `${height}px`,
    transform: 'none',
    margin: '0',
  });
}

function _renderShell() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = MODAL_ID;
  modal.className = 'modal logbook-atlas-modal';
  document.body.appendChild(modal);
  Modals.register(MODAL_ID, {
    railBtnId: 'rail-logbook-atlas',
    sidebarBtnId: 'tool-logbook-atlas-btn',
    label: 'People & Places',
    icon: _iconAtlas(14),
    restoreFn: () => {
      _open = true;
      modal.classList.remove('hidden');
    },
    closeFn: closeAtlas,
  });
  return modal;
}

function _wireWindow(modal) {
  const content = modal?.querySelector('.logbook-atlas-content');
  const header = modal?.querySelector('.logbook-atlas-header');
  if (!modal || !content || !header) return;
  _restoreWindowRect(modal);
  makeWindowDraggable(modal, {
    content,
    header,
    skipSelector: 'button, input, select, textarea, label',
    mobileSkip: 900,
    enableDock: true,
    onDragEnd: () => _captureWindowRect(modal),
  });
}

function _tabLabel(tab) {
  return tab === 'map' ? 'Map' : tab[0].toUpperCase() + tab.slice(1);
}

function _ensureAtlasContent(modal) {
  if (modal.querySelector('.logbook-atlas-content')) return false;
  modal.innerHTML = `
    <div class="modal-content logbook-atlas-content" role="dialog" aria-label="Logbook People and Places">
      <div class="modal-header logbook-atlas-header">
        <h4>People & Places</h4>
        <button type="button" class="close-btn" id="logbook-atlas-close" title="Close" aria-label="Close">&#x2716;</button>
      </div>
      <div data-atlas-error-slot></div>
      <div data-atlas-status-slot></div>
      <div class="logbook-atlas-toolbar">
        <div class="logbook-atlas-tabs">
          ${['people', 'locations', 'map', 'connections'].map(tab => `<button type="button" class="logbook-tab" data-atlas-tab="${tab}">${_tabLabel(tab)}</button>`).join('')}
        </div>
        <button type="button" class="cal-btn" id="logbook-atlas-refresh">Refresh</button>
      </div>
      <div class="modal-body logbook-atlas-body"></div>
    </div>
  `;
  Modals.injectMinimizeButton(modal, MODAL_ID);
  _wireWindow(modal);
  _bindChrome(modal);
  return true;
}

function _render() {
  const modal = _renderShell();
  _captureWindowRect(modal);
  _ensureAtlasContent(modal);
  modal.querySelector('[data-atlas-error-slot]').innerHTML =
    _error ? `<div class="logbook-atlas-error">${_e(_error)}</div>` : '';
  modal.querySelector('[data-atlas-status-slot]').innerHTML =
    _busy ? '<div class="logbook-atlas-status">Saving...</div>' : '';
  modal.querySelectorAll('[data-atlas-tab]').forEach(btn => {
    const active = btn.dataset.atlasTab === _tab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const body = modal.querySelector('.logbook-atlas-body');
  body.dataset.tab = _tab;
  body.innerHTML = _bodyHtml();
  _bindBody();
}

function _bodyHtml() {
  if (_tab === 'locations') return _locationsTabHtml();
  if (_tab === 'map') return _mapTabHtml();
  if (_tab === 'connections') return _connectionsTabHtml();
  return _peopleTabHtml();
}

function _meta(item) {
  const count = Number(item?.mention_count || 0);
  const bits = [`${count} ${count === 1 ? 'entry' : 'entries'}`];
  if (item?.last_mentioned) bits.push(`last ${item.last_mentioned}`);
  return bits.join(' | ');
}

function _reconnect(item) {
  const suggestion = item?.reconnect_suggestion || null;
  return suggestion && suggestion.message ? suggestion : null;
}

function _reconnectPeople() {
  return (_atlas.people || [])
    .filter(person => _reconnect(person))
    .sort((a, b) => (
      Number(b.days_since_mentioned || 0) - Number(a.days_since_mentioned || 0) ||
      String(a.display_name || '').localeCompare(String(b.display_name || ''))
    ))
    .slice(0, 8);
}

function _reconnectCardHtml(person, compact = false) {
  const suggestion = _reconnect(person);
  if (!suggestion) return '';
  return `
    <button type="button" class="logbook-reconnect-card ${compact ? 'compact' : ''}" data-reconnect-person="${_e(person.id || '')}">
      <strong>${_e(person.display_name || person.name || 'Person')}</strong>
      <span>${_e(suggestion.message)}</span>
    </button>
  `;
}

function _personConnectionsDetailHtml(detail) {
  const connections = _personDetail?.connections || [];
  const visible = connections.filter(conn => conn.status !== 'hidden');
  if (visible.length) {
    return visible.map(_connectionCardHtml).join('');
  }
  const summaries = Array.isArray(detail?.connections_summary)
    ? detail.connections_summary.filter(item => item && item.status !== 'hidden')
    : [];
  if (!summaries.length) return '<div class="logbook-empty">No known connections yet.</div>';
  return summaries.map(summary => {
    const other = summary.other_person?.display_name || 'Person';
    const status = summary.status === 'accepted' ? 'accepted' : 'suggested';
    return `
      <div class="logbook-person-connection-row ${status}">
        <strong>${_logbookIcon('person', 12)}${_e(other)}</strong>
        <span>${_e(_connectionTypeLabel(summary.connection_type))}${summary.confidence ? ` - ${_e(summary.confidence)}% confidence` : ''}</span>
      </div>
    `;
  }).join('');
}

function _personFactsHtml(detail) {
  const facts = Array.isArray(detail?.facts)
    ? detail.facts.filter(fact => fact && fact.status !== 'rejected')
    : [];
  if (!facts.length) return '<div class="logbook-empty">No saved facts yet.</div>';
  return facts.map(fact => {
    const dates = [];
    if (fact.source_entry_date) dates.push(`first ${fact.source_entry_date}`);
    if (fact.last_seen_date && fact.last_seen_date !== fact.source_entry_date) dates.push(`last ${fact.last_seen_date}`);
    const confidence = fact.confidence ? `${Math.max(0, Math.min(100, Number(fact.confidence || 0)))}%` : '';
    return `
      <div class="logbook-person-fact">
        <strong>${_e(fact.label || _factTypeLabel(fact.fact_type))}</strong>
        <span>${_e(fact.value_text || '')}</span>
        <em>${_e([dates.join(' · '), confidence].filter(Boolean).join(' · '))}</em>
      </div>
    `;
  }).join('');
}

function _personFactFormHtml() {
  if (_creatingPerson) return '<div class="logbook-empty">Save this person before adding facts.</div>';
  return `
    <form class="logbook-person-fact-form" id="atlas-person-fact-form">
      <div class="logbook-person-fact-form-grid">
        <label>Type<select id="atlas-person-fact-type" class="logbook-select">${_personFactTypeOptionsHtml('note')}</select></label>
        <label>Label<input id="atlas-person-fact-label" class="memory-search-input" placeholder="Optional"></label>
        <label class="logbook-person-fact-form-value">Value<input id="atlas-person-fact-value" class="memory-search-input" placeholder="What should be remembered?"></label>
      </div>
      <div class="logbook-person-fact-form-actions">
        <button type="submit" class="cal-btn cal-btn-primary" id="atlas-add-person-fact">Add fact</button>
      </div>
    </form>
  `;
}

function _personNameById(personId) {
  const person = (_atlas.people || []).find(item => item.id === personId);
  return person?.display_name || person?.canonical_name || 'Person';
}

function _personMergeOptionsHtml() {
  return (_atlas.people || [])
    .filter(person => person.id && person.id !== _selectedPersonId)
    .map(person => `<option value="${_e(person.id)}">${_e(person.display_name || 'Person')}</option>`)
    .join('');
}

function _personMergeHtml(detail) {
  if (_creatingPerson) return '';
  const options = _personMergeOptionsHtml();
  if (!options) return '';
  const currentName = detail?.display_name || 'this person';
  return `
    <div class="logbook-subtitle">Merge duplicates</div>
    <div class="logbook-person-merge">
      <div class="logbook-person-merge-grid">
        <label>Duplicate<select id="atlas-person-merge-other" class="logbook-select">${options}</select></label>
        <button type="button" class="cal-btn cal-btn-primary" id="atlas-merge-keep-current">Keep ${_e(currentName)}</button>
        <button type="button" class="cal-btn" id="atlas-merge-keep-other">Keep duplicate</button>
      </div>
    </div>
  `;
}

function _peopleTabHtml() {
  const reconnect = _reconnectPeople().map(person => _reconnectCardHtml(person, true)).join('');
  const rows = _visiblePeople().map(person => `
    <button type="button" class="logbook-atlas-row ${person.id === _selectedPersonId ? 'active' : ''} ${_reconnect(person) ? 'needs-reconnect' : ''}" data-person-id="${_e(person.id)}">
      <strong>${_logbookIcon('person', 12)}${_e(person.display_name || 'Person')}</strong>
      <span>${_e(_reconnect(person)?.message || person.relationship_label || _meta(person))}</span>
    </button>
  `).join('') || '<div class="logbook-empty">No people yet.</div>';
  return `
    <aside class="logbook-atlas-list">
      <div class="logbook-atlas-list-tools">
        <input id="atlas-people-search" class="memory-search-input" placeholder="Find people" value="${_e(_peopleSearch)}">
        <button type="button" class="cal-btn" id="atlas-new-person">New person</button>
      </div>
      ${reconnect ? `<div class="logbook-reconnect-list"><div class="logbook-subtitle">Reconnect</div>${reconnect}</div>` : ''}
      <div class="logbook-atlas-scroll">${rows}</div>
    </aside>
    <section class="logbook-atlas-detail">${_personDetailHtml()}</section>
  `;
}

function _personDetailHtml() {
  const detail = _creatingPerson
    ? { display_name: '', aliases: [], relationship_label: '', notes: '', llm_context: '', contact_snapshot: null }
    : _personDetail?.person || (_atlas.people || []).find(p => p.id === _selectedPersonId);
  if (!detail) return '<div class="logbook-empty">Select a person.</div>';
  const aliases = (detail.aliases || []).join(', ');
  const snapshot = detail.contact_snapshot || null;
  const entries = (_personDetail?.entries || []).map(entry => `
    <button type="button" class="logbook-atlas-entry" data-entry-date="${_e(entry.entry_date)}">
      <strong>${_e(entry.entry_date)}</strong>
      <span>${_e(entry.summary || entry.title || 'Daily log')}</span>
    </button>
  `).join('') || '<div class="logbook-empty">No linked entries.</div>';
  const candidates = _contactCandidates.map(c => `
    <div class="logbook-contact-candidate">
      <div><strong>${_e(c.name || 'Contact')}</strong><span>${_e((c.emails || []).join(', '))}</span></div>
      <button type="button" class="cal-btn" data-link-contact="${_e(c.uid)}">Link</button>
    </div>
  `).join('');
  return `
    <div class="logbook-atlas-form">
      <div class="logbook-section-head"><h5>${_creatingPerson ? 'New person' : 'Person'}</h5><button type="button" class="cal-btn cal-btn-primary" id="atlas-save-person">Save</button></div>
      ${_reconnectCardHtml(detail)}
      <label>Name<input id="atlas-person-name" class="memory-search-input" value="${_e(detail.display_name || '')}"></label>
      <label>Aliases<input id="atlas-person-aliases" class="memory-search-input" value="${_e(aliases)}" placeholder="Jan, JP"></label>
      <label>Relation<input id="atlas-person-relation" class="memory-search-input" list="atlas-person-relation-types" value="${_e(detail.relationship_label || '')}" placeholder="Choose or type relation">${_personRelationOptionsHtml()}</label>
      <label>Notes<textarea id="atlas-person-notes" class="logbook-atlas-text">${_e(detail.notes || '')}</textarea></label>
      <label>LLM context<textarea id="atlas-person-context" class="logbook-atlas-text" placeholder="Context the assistant may use about this person.">${_e(detail.llm_context || '')}</textarea></label>
      <div class="logbook-subtitle">Facts</div>
      ${_personFactFormHtml()}
      <div class="logbook-atlas-person-facts">${_personFactsHtml(detail)}</div>
      ${_personMergeHtml(detail)}
      <div class="logbook-subtitle">Connections</div>
      <div class="logbook-atlas-person-connections">${_personConnectionsDetailHtml(detail)}</div>
      <div class="logbook-atlas-contact">
        <div class="logbook-subtitle">Linked contact</div>
        ${_creatingPerson ? '<div class="logbook-empty">Save this person before linking a contact.</div>' : snapshot ? `<div class="logbook-contact-linked"><strong>${_e(snapshot.name || detail.display_name)}</strong><span>${_e((snapshot.emails || []).join(', '))}</span><button type="button" class="cal-btn" id="atlas-unlink-contact">Unlink</button></div>` : '<div class="logbook-empty">No linked contact.</div>'}
        ${!_creatingPerson && _atlas.contacts_available ? `<div class="logbook-directory-tools"><input id="atlas-contact-search" class="memory-search-input" placeholder="Find contact" value="${_e(_contactQuery)}"><button type="button" class="cal-btn" id="atlas-contact-search-btn">Search</button></div>${candidates}` : !_creatingPerson ? '<div class="logbook-empty">Contacts unavailable for this user.</div>' : ''}
      </div>
      <div class="logbook-subtitle">Recent entries</div>
      <div class="logbook-atlas-entry-list">${entries}</div>
    </div>
  `;
}

function _locationsTabHtml() {
  const types = _locationTypes().map(type => `<option value="${_e(type)}" ${_locationTypeFilter === type ? 'selected' : ''}>${_e(type)}</option>`).join('');
  const rows = _visibleLocations().map(location => `
    <button type="button" class="logbook-atlas-row ${location.id === _selectedLocationId ? 'active' : ''} ${location.hidden ? 'is-hidden' : ''}" data-location-id="${_e(location.id)}">
      <strong>${_logbookIcon('location', 12)}${_e(location.display_name || 'Place')}${location.hidden ? '<em>Hidden</em>' : ''}</strong>
      <span>${_e(location.hidden ? 'Hidden from linking' : location.address || location.location_type || _meta(location))}</span>
    </button>
  `).join('') || '<div class="logbook-empty">No places yet.</div>';
  return `
    <aside class="logbook-atlas-list">
      <div class="logbook-atlas-list-tools">
        <input id="atlas-location-search" class="memory-search-input" placeholder="Find places" value="${_e(_locationSearch)}">
        <button type="button" class="cal-btn" id="atlas-new-location">New place</button>
      </div>
      <select id="atlas-location-type" class="logbook-select"><option value="">Any type</option>${types}</select>
      <div class="logbook-atlas-scroll">${rows}</div>
    </aside>
    <section class="logbook-atlas-detail">${_locationDetailHtml()}</section>
  `;
}

function _locationPinDetailsHtml(detail) {
  const pinned = _hasLocationPin(detail);
  return `
    <details class="logbook-location-pin-details">
      <summary><span>Map pin</span><em>${pinned ? 'Pinned' : 'Not pinned'}</em></summary>
      <div class="logbook-atlas-coordinates">
        <label>Latitude<input id="atlas-location-lat" class="memory-search-input" type="number" step="any" value="${detail.latitude ?? ''}"></label>
        <label>Longitude<input id="atlas-location-lon" class="memory-search-input" type="number" step="any" value="${detail.longitude ?? ''}"></label>
      </div>
    </details>
  `;
}

function _locationGeocodeResultsHtml() {
  if (!_locationGeocodeResults.length) return '';
  return `
    <div class="logbook-location-geocode-results">
      <div class="logbook-subtitle">Matches${_locationGeocodeQuery ? ` for ${_e(_locationGeocodeQuery)}` : ''}</div>
      ${_locationGeocodeResults.map((result, index) => `
        <button type="button" class="logbook-geocode-result" data-geocode-result="${index}">
          <strong>${_logbookIcon('location', 12)}${_e(result.label || 'Map result')}</strong>
          <span>${_e(result.address || '')}</span>
          <em>${Number(result.latitude).toFixed(5)}, ${Number(result.longitude).toFixed(5)}</em>
        </button>
      `).join('')}
    </div>
  `;
}

function _locationDetailHtml() {
  const detail = _creatingLocation
    ? { display_name: '', aliases: [], location_type: '', address: '', latitude: null, longitude: null, notes: '', llm_context: '' }
    : _locationDetail?.location || (_atlas.locations || []).find(l => l.id === _selectedLocationId);
  if (!detail) return '<div class="logbook-empty">Select a place.</div>';
  const aliases = (detail.aliases || []).join(', ');
  const mentionCount = Number(detail.mention_count || 0);
  const actionButton = _creatingLocation
    ? ''
    : detail.hidden
      ? `<button type="button" class="cal-btn" id="atlas-unhide-location">Unhide</button>${mentionCount === 0 ? '<button type="button" class="cal-btn" id="atlas-delete-location">Delete</button>' : ''}`
      : mentionCount === 0
        ? '<button type="button" class="cal-btn" id="atlas-delete-location">Delete</button>'
        : '<button type="button" class="cal-btn" id="atlas-hide-location">Hide from linking</button>';
  const entries = (_locationDetail?.entries || []).map(entry => `
    <button type="button" class="logbook-atlas-entry" data-entry-date="${_e(entry.entry_date)}">
      <strong>${_e(entry.entry_date)}</strong>
      <span>${_e(entry.summary || entry.title || 'Daily log')}</span>
    </button>
  `).join('') || '<div class="logbook-empty">No linked entries.</div>';
  return `
    <div class="logbook-atlas-form">
      <div class="logbook-section-head"><h5>${_creatingLocation ? 'New place' : 'Place'}${detail.hidden ? ' <span class="logbook-muted-badge">Hidden</span>' : ''}</h5><div class="logbook-atlas-actions">${actionButton}<button type="button" class="cal-btn cal-btn-primary" id="atlas-save-location">Save</button></div></div>
      ${detail.hidden ? '<div class="logbook-ai-disabled">This place is hidden from linking and autocomplete. Existing entry history stays intact.</div>' : ''}
      <label>Name<input id="atlas-location-name" class="memory-search-input" value="${_e(detail.display_name || '')}"></label>
      <label>Aliases<input id="atlas-location-aliases" class="memory-search-input" value="${_e(aliases)}" placeholder="office, gym"></label>
      <label>Type<input id="atlas-location-kind" class="memory-search-input" value="${_e(detail.location_type || '')}" placeholder="home, work, gym"></label>
      <div class="logbook-location-address-tools">
        <label>Address<input id="atlas-location-address" class="memory-search-input" value="${_e(detail.address || '')}"></label>
        <button type="button" class="cal-btn" id="atlas-geocode-location">Find coordinates</button>
      </div>
      <div id="atlas-location-geocode-results">${_locationGeocodeResultsHtml()}</div>
      ${_locationPinDetailsHtml(detail)}
      <label>Notes<textarea id="atlas-location-notes" class="logbook-atlas-text">${_e(detail.notes || '')}</textarea></label>
      <label>LLM context<textarea id="atlas-location-context" class="logbook-atlas-text" placeholder="Context the assistant may use about this place.">${_e(detail.llm_context || '')}</textarea></label>
      <div class="logbook-subtitle">Recent entries</div>
      <div class="logbook-atlas-entry-list">${entries}</div>
    </div>
  `;
}

function _mapPlaceRowsHtml(locations, emptyText) {
  if (!locations.length) return `<div class="logbook-empty">${_e(emptyText)}</div>`;
  return locations.map(location => {
    const address = String(location.address || '').trim();
    const type = String(location.location_type || '').trim();
    return `
      <div class="logbook-map-place-row">
        <button type="button" class="logbook-map-place-main" data-map-location="${_e(location.id)}">
          <strong>${_logbookIcon('location', 12)}${_e(location.display_name || 'Place')}</strong>
          <span>${_e(address || type || _meta(location))}</span>
        </button>
        <div class="logbook-map-place-actions">
          ${_locationMapSearchLink(location)}
          <button type="button" class="cal-btn" data-map-location="${_e(location.id)}">${_hasLocationPin(location) ? 'Edit' : 'Set pin'}</button>
        </div>
      </div>
    `;
  }).join('');
}

function _mapLocations() {
  return (_atlas.locations || []).filter(location => !location.hidden);
}

function _mapStageHtml(locations = _mapLocations()) {
  return renderCoordinateMap(locations, {
    labelKey: 'display_name',
    pinDataAttribute: 'data-map-location',
    emptyText: 'No pinned places yet.',
    tileConfig: _mapConfig,
    zoomOffset: _mapZoomOffset,
  });
}

function _refreshMapStage() {
  const stage = document.querySelector(`#${MODAL_ID} .logbook-map-stage`);
  if (!stage) {
    _render();
    return;
  }
  stage.innerHTML = _mapStageHtml();
  _bindMapActions(stage);
}

function _mapTabHtml() {
  const locations = _mapLocations();
  const points = pointsWithCoordinates(locations);
  const noCoords = pointsWithoutCoordinates(locations);
  const addressOnly = noCoords.filter(location => String(location.address || '').trim());
  const noAddress = noCoords.filter(location => !String(location.address || '').trim());
  const map = _mapStageHtml(locations);
  const mapMode = _mapConfig?.tiles_enabled ? `${_mapConfig.provider || 'tiles'}` : 'local grid';
  const tileError = _mapConfig?.error ? `<div class="logbook-ai-warning">${_e(_mapConfig.error)}</div>` : '';
  return `
    <section class="map-panel">
      <div class="logbook-section-head"><h5>Map</h5><span>${points.length} pinned · ${addressOnly.length} address-only</span></div>
      <div class="logbook-map-mode">${_e(mapMode)}</div>
      ${tileError}
      <div class="logbook-map-layout">
        <div class="logbook-map-stage">${map}</div>
        <aside class="logbook-map-side">
          <div class="logbook-subtitle">Pinned places</div>
          <div class="logbook-map-place-list">${_mapPlaceRowsHtml(points, 'No pinned places yet.')}</div>
          <div class="logbook-subtitle">Address-only</div>
          <div class="logbook-map-place-list">${_mapPlaceRowsHtml(addressOnly, 'No address-only places.')}</div>
          <div class="logbook-subtitle">Missing address</div>
          <div class="logbook-map-place-list">${_mapPlaceRowsHtml(noAddress, 'All places have an address or pin.')}</div>
        </aside>
      </div>
    </section>
  `;
}

function _connectionsTabHtml() {
  const visible = (_atlas.connections || [])
    .filter(conn => conn.status !== 'hidden')
  const rows = visible.map(_connectionCardHtml).join('');
  const canCreate = (_atlas.people || []).length >= 2;
  const form = _showConnectionForm || _editingConnectionId
    ? _connectionFormHtml()
    : (!canCreate ? '<div class="logbook-empty">Add at least two people before creating a connection.</div>' : '');
  return `
    <section class="logbook-atlas-connections">
      <div class="logbook-section-head">
        <h5>Connections</h5>
        <div class="logbook-atlas-actions">
          <span>${visible.length} visible</span>
          ${canCreate && !_showConnectionForm && !_editingConnectionId ? '<button type="button" class="cal-btn" id="atlas-new-connection">New connection</button>' : ''}
        </div>
      </div>
      ${form}
      ${rows || '<div class="logbook-empty">No connection suggestions.</div>'}
    </section>
  `;
}

function _bindChrome(root = document) {
  root.querySelector('#logbook-atlas-close')?.addEventListener('click', closeAtlas);
  root.querySelector('#logbook-atlas-refresh')?.addEventListener('click', () => openAtlas({ refresh: true }).catch(_setError));
  root.querySelectorAll('[data-atlas-tab]').forEach(btn => {
    btn.addEventListener('click', async () => {
      _tab = btn.dataset.atlasTab || 'people';
      _error = '';
      if (_tab === 'people' && _selectedPersonId && !_personDetail) await _selectPerson(_selectedPersonId);
      else if (_tab === 'locations' && _selectedLocationId && !_locationDetail) await _selectLocation(_selectedLocationId);
      else _render();
    });
  });
}

function _bindBody() {
  _bindPeople();
  _bindLocations();
  _bindMap();
  _bindConnections();
}

function _bindPeople() {
  const search = document.getElementById('atlas-people-search');
  search?.addEventListener('input', () => {
    _peopleSearch = search.value;
    _render();
  });
  document.querySelectorAll('[data-person-id]').forEach(btn => {
    btn.addEventListener('click', () => _selectPerson(btn.dataset.personId).catch(_setError));
  });
  document.querySelectorAll('[data-reconnect-person]').forEach(btn => {
    btn.addEventListener('click', () => _selectPerson(btn.dataset.reconnectPerson).catch(_setError));
  });
  document.getElementById('atlas-new-person')?.addEventListener('click', _newPerson);
  document.getElementById('atlas-save-person')?.addEventListener('click', () => _savePerson().catch(_setError));
  document.getElementById('atlas-person-fact-form')?.addEventListener('submit', event => {
    event.preventDefault();
    _addPersonFact().catch(_setError);
  });
  document.getElementById('atlas-merge-keep-current')?.addEventListener('click', () => _mergeSelectedPerson('keep-current').catch(_setError));
  document.getElementById('atlas-merge-keep-other')?.addEventListener('click', () => _mergeSelectedPerson('keep-other').catch(_setError));
  document.getElementById('atlas-unlink-contact')?.addEventListener('click', () => _unlinkContact().catch(_setError));
  const contactSearch = document.getElementById('atlas-contact-search');
  contactSearch?.addEventListener('input', () => {
    _contactQuery = contactSearch.value;
    clearTimeout(contactSearch._timer);
    contactSearch._timer = setTimeout(() => _searchContacts().catch(_setError), 250);
  });
  document.getElementById('atlas-contact-search-btn')?.addEventListener('click', () => _searchContacts().catch(_setError));
  document.querySelectorAll('[data-link-contact]').forEach(btn => {
    btn.addEventListener('click', () => _linkContact(btn.dataset.linkContact).catch(_setError));
  });
  document.querySelectorAll('[data-entry-date]').forEach(btn => {
    btn.addEventListener('click', () => {
      window.history.pushState({}, '', `/logbook?date=${encodeURIComponent(btn.dataset.entryDate || '')}`);
      import('./logbook.js').then(mod => mod.default?.openLogbook?.()).catch(() => {});
    });
  });
}

function _bindLocations() {
  const search = document.getElementById('atlas-location-search');
  search?.addEventListener('input', () => {
    _locationSearch = search.value;
    _render();
  });
  document.getElementById('atlas-location-type')?.addEventListener('change', e => {
    _locationTypeFilter = e.target.value || '';
    _render();
  });
  document.querySelectorAll('[data-location-id]').forEach(btn => {
    btn.addEventListener('click', () => _selectLocation(btn.dataset.locationId).catch(_setError));
  });
  document.getElementById('atlas-new-location')?.addEventListener('click', _newLocation);
  document.getElementById('atlas-save-location')?.addEventListener('click', () => _saveLocation().catch(_setError));
  document.getElementById('atlas-geocode-location')?.addEventListener('click', () => _geocodeLocation().catch(_setError));
  _bindLocationGeocodeResults();
  document.getElementById('atlas-delete-location')?.addEventListener('click', () => _deleteSelectedLocation().catch(_setError));
  document.getElementById('atlas-hide-location')?.addEventListener('click', () => _hideSelectedLocation().catch(_setError));
  document.getElementById('atlas-unhide-location')?.addEventListener('click', () => _unhideSelectedLocation().catch(_setError));
}

function _bindLocationGeocodeResults() {
  document.querySelectorAll('[data-geocode-result]').forEach(btn => {
    btn.addEventListener('click', () => _applyGeocodeResult(Number(btn.dataset.geocodeResult || 0)));
  });
}

function _bindMapActions(root = document) {
  root.querySelectorAll('[data-map-location]').forEach(btn => {
    btn.addEventListener('click', () => {
      _tab = 'locations';
      _selectLocation(btn.dataset.mapLocation).catch(_setError);
    });
  });
  root.querySelectorAll('[data-map-zoom]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.mapZoom || '';
      if (action === 'in') _mapZoomOffset = Math.min(5, _mapZoomOffset + 1);
      else if (action === 'out') _mapZoomOffset = Math.max(-5, _mapZoomOffset - 1);
      else _mapZoomOffset = 0;
      _refreshMapStage();
    });
  });
}

function _bindMap() {
  _bindMapActions(document);
}

function _bindConnections() {
  document.getElementById('atlas-new-connection')?.addEventListener('click', () => {
    _editingConnectionId = '';
    _connectionDraft = _defaultConnectionDraft();
    _showConnectionForm = true;
    _render();
  });
  document.getElementById('atlas-cancel-connection')?.addEventListener('click', () => {
    _editingConnectionId = '';
    _connectionDraft = null;
    _showConnectionForm = false;
    _render();
  });
  document.getElementById('atlas-save-connection')?.addEventListener('click', () => _saveConnection().catch(_setError));
  document.querySelectorAll('[data-edit-connection]').forEach(btn => {
    btn.addEventListener('click', () => {
      const conn = _connectionById(btn.dataset.editConnection);
      if (!conn) return;
      _tab = 'connections';
      _editingConnectionId = conn.id;
      _connectionDraft = _draftFromConnection(conn);
      _showConnectionForm = true;
      _render();
    });
  });
  document.querySelectorAll('[data-connection-person]').forEach(btn => {
    btn.addEventListener('click', () => {
      _tab = 'people';
      _selectPerson(btn.dataset.connectionPerson).catch(_setError);
    });
  });
  document.querySelectorAll('[data-accept-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.acceptConnection, 'accept').catch(_setError));
  });
  document.querySelectorAll('[data-hide-connection]').forEach(btn => {
    btn.addEventListener('click', () => _connectionAction(btn.dataset.hideConnection, 'hide').catch(_setError));
  });
}

function _aliases(value) {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean);
}

async function _savePerson() {
  if (!_selectedPersonId && !_creatingPerson) return;
  const payload = {
    display_name: document.getElementById('atlas-person-name')?.value || '',
    aliases: _aliases(document.getElementById('atlas-person-aliases')?.value),
    relationship_label: document.getElementById('atlas-person-relation')?.value || null,
    notes: document.getElementById('atlas-person-notes')?.value || null,
    llm_context: document.getElementById('atlas-person-context')?.value || null,
  };
  if (!payload.display_name.trim()) throw new Error('Name is required');
  _busy = true;
  _render();
  try {
    const result = _creatingPerson
      ? await createPerson(payload)
      : await updatePerson(_selectedPersonId, payload);
    _creatingPerson = false;
    _selectedPersonId = result.person.id;
    await _loadAtlas();
    _personDetail = await getPerson(result.person.id, new URLSearchParams({ limit: '30' }));
    uiModule?.showToast?.(result.duplicate ? 'Opened existing person' : 'Saved');
  } finally {
    _busy = false;
    _render();
  }
}

async function _addPersonFact() {
  if (!_selectedPersonId || _creatingPerson) return;
  const valueText = (document.getElementById('atlas-person-fact-value')?.value || '').trim();
  if (!valueText) throw new Error('Fact value is required');
  const payload = {
    fact_type: document.getElementById('atlas-person-fact-type')?.value || 'note',
    label: (document.getElementById('atlas-person-fact-label')?.value || '').trim() || null,
    value_text: valueText,
    confidence: 100,
    status: 'active',
  };
  _busy = true;
  _render();
  try {
    const result = await createPersonFact(_selectedPersonId, payload);
    await _loadAtlas();
    _personDetail = await getPerson(_selectedPersonId, new URLSearchParams({ limit: '30' }));
    uiModule?.showToast?.(result.duplicate ? 'Fact already exists' : 'Fact added');
  } finally {
    _busy = false;
    _render();
  }
}

async function _mergeSelectedPerson(mode) {
  if (!_selectedPersonId || _creatingPerson) return;
  const otherId = document.getElementById('atlas-person-merge-other')?.value || '';
  if (!otherId || otherId === _selectedPersonId) throw new Error('Choose two different people');
  const keepCurrent = mode === 'keep-current';
  const sourceId = keepCurrent ? otherId : _selectedPersonId;
  const targetId = keepCurrent ? _selectedPersonId : otherId;
  const sourceName = _personNameById(sourceId);
  const targetName = _personNameById(targetId);
  if (!window.confirm(`Merge "${sourceName}" into "${targetName}"?`)) return;
  _busy = true;
  _render();
  try {
    const result = await mergePeople({
      source_person_id: sourceId,
      target_person_id: targetId,
    });
    await _loadAtlas();
    _creatingPerson = false;
    _selectedPersonId = result.person?.id || targetId;
    _personDetail = await getPerson(_selectedPersonId, new URLSearchParams({ limit: '30' }));
    _contactCandidates = [];
    _contactQuery = '';
    uiModule?.showToast?.(`Merged into ${_personNameById(_selectedPersonId)}`);
  } finally {
    _busy = false;
    _render();
  }
}

async function _saveLocation() {
  if (!_selectedLocationId && !_creatingLocation) return;
  const latRaw = document.getElementById('atlas-location-lat')?.value || '';
  const lonRaw = document.getElementById('atlas-location-lon')?.value || '';
  const payload = {
    display_name: document.getElementById('atlas-location-name')?.value || '',
    aliases: _aliases(document.getElementById('atlas-location-aliases')?.value),
    location_type: document.getElementById('atlas-location-kind')?.value || null,
    address: document.getElementById('atlas-location-address')?.value || null,
    latitude: latRaw === '' ? null : Number(latRaw),
    longitude: lonRaw === '' ? null : Number(lonRaw),
    notes: document.getElementById('atlas-location-notes')?.value || null,
    llm_context: document.getElementById('atlas-location-context')?.value || null,
  };
  if (!payload.display_name.trim()) throw new Error('Name is required');
  _busy = true;
  _render();
  try {
    const result = _creatingLocation
      ? await createLocation(payload)
      : await updateLocation(_selectedLocationId, payload);
    _creatingLocation = false;
    _selectedLocationId = result.location.id;
    _locationGeocodeResults = [];
    _locationGeocodeQuery = '';
    await _loadAtlas();
    _locationDetail = await getLocation(result.location.id, new URLSearchParams({ limit: '30' }));
    uiModule?.showToast?.(result.duplicate ? 'Opened existing place' : 'Saved');
  } finally {
    _busy = false;
    _render();
  }
}

async function _geocodeLocation() {
  const addressInput = document.getElementById('atlas-location-address');
  const nameInput = document.getElementById('atlas-location-name');
  const query = (addressInput?.value || nameInput?.value || '').trim();
  if (query.length < 3) throw new Error('Add an address or place name first');
  const button = document.getElementById('atlas-geocode-location');
  if (button) {
    button.disabled = true;
    button.textContent = 'Finding...';
  }
  try {
    const result = await geocodeAddress(query, 5);
    _locationGeocodeResults = result.results || [];
    _locationGeocodeQuery = query;
    const holder = document.getElementById('atlas-location-geocode-results');
    if (holder) {
      holder.innerHTML = _locationGeocodeResultsHtml();
      _bindLocationGeocodeResults();
    }
    if (!_locationGeocodeResults.length) uiModule?.showToast?.('No local matches found');
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'Find coordinates';
    }
  }
}

function _applyGeocodeResult(index) {
  const result = _locationGeocodeResults[index];
  if (!result) return;
  const latInput = document.getElementById('atlas-location-lat');
  const lonInput = document.getElementById('atlas-location-lon');
  const addressInput = document.getElementById('atlas-location-address');
  if (latInput) latInput.value = String(result.latitude ?? '');
  if (lonInput) lonInput.value = String(result.longitude ?? '');
  if (addressInput && !addressInput.value.trim() && result.address) addressInput.value = result.address;
  const pinDetails = document.querySelector('.logbook-location-pin-details');
  if (pinDetails) pinDetails.open = true;
  uiModule?.showToast?.('Coordinates filled');
}

async function _deleteSelectedLocation() {
  if (!_selectedLocationId) return;
  const detail = _locationDetail?.location || (_atlas.locations || []).find(l => l.id === _selectedLocationId);
  if (Number(detail?.mention_count || 0) > 0) throw new Error('Place has linked entries; hide it instead');
  if (!window.confirm('Delete this unused place?')) return;
  _busy = true;
  _render();
  try {
    await deleteLocation(_selectedLocationId);
    _selectedLocationId = '';
    _locationDetail = null;
    await _loadAtlas();
    if (_atlas.locations?.length) {
      _selectedLocationId = _atlas.locations[0].id;
      _locationDetail = await getLocation(_selectedLocationId, new URLSearchParams({ limit: '30' }));
    }
    uiModule?.showToast?.('Deleted place');
  } finally {
    _busy = false;
    _render();
  }
}

async function _hideSelectedLocation() {
  if (!_selectedLocationId) return;
  if (!window.confirm('Hide this place from linking and autocomplete?')) return;
  _busy = true;
  _render();
  try {
    await hideLocation(_selectedLocationId);
    await _loadAtlas();
    _locationDetail = await getLocation(_selectedLocationId, new URLSearchParams({ limit: '30' }));
    uiModule?.showToast?.('Hidden from linking');
  } finally {
    _busy = false;
    _render();
  }
}

async function _unhideSelectedLocation() {
  if (!_selectedLocationId) return;
  _busy = true;
  _render();
  try {
    await unhideLocation(_selectedLocationId);
    await _loadAtlas();
    _locationDetail = await getLocation(_selectedLocationId, new URLSearchParams({ limit: '30' }));
    uiModule?.showToast?.('Visible for linking');
  } finally {
    _busy = false;
    _render();
  }
}

async function _searchContacts() {
  const result = await listContactCandidates(_contactQuery);
  _contactCandidates = result.contacts || [];
  _atlas.contacts_available = Boolean(result.available);
  _render();
}

function _connectionPayload({ includePeople = false } = {}) {
  const strengthRaw = document.getElementById('atlas-connection-strength')?.value || '';
  const confidenceRaw = document.getElementById('atlas-connection-confidence')?.value || '';
  const payload = {
    connection_type: document.getElementById('atlas-connection-type')?.value || 'unknown',
    status: document.getElementById('atlas-connection-status')?.value || 'accepted',
    strength: strengthRaw === '' ? null : Number(strengthRaw),
    confidence: confidenceRaw === '' ? null : Number(confidenceRaw),
    description: document.getElementById('atlas-connection-description')?.value || null,
  };
  if (includePeople) {
    payload.person_a_id = document.getElementById('atlas-connection-person-a')?.value || '';
    payload.person_b_id = document.getElementById('atlas-connection-person-b')?.value || '';
    if (!payload.person_a_id || !payload.person_b_id) throw new Error('Choose two people');
    if (payload.person_a_id === payload.person_b_id) throw new Error('Choose two different people');
  }
  return payload;
}

async function _saveConnection() {
  const editing = Boolean(_editingConnectionId);
  const payload = _connectionPayload({ includePeople: !editing });
  _busy = true;
  _render();
  try {
    const result = editing
      ? await saveConnection(_editingConnectionId, payload)
      : await createConnection(payload);
    await _loadAtlas();
    if (_selectedPersonId) {
      _personDetail = await getPerson(_selectedPersonId, new URLSearchParams({ limit: '30' }));
    }
    _editingConnectionId = '';
    _connectionDraft = null;
    _showConnectionForm = false;
    uiModule?.showToast?.(result.duplicate ? 'Updated existing connection' : 'Saved');
  } finally {
    _busy = false;
    _render();
  }
}

async function _linkContact(contactUid) {
  if (!_selectedPersonId || !contactUid) return;
  await linkPersonContact(_selectedPersonId, contactUid);
  await _loadAtlas();
  _personDetail = await getPerson(_selectedPersonId, new URLSearchParams({ limit: '30' }));
  _contactCandidates = [];
  uiModule?.showToast?.('Linked');
  _render();
}

async function _unlinkContact() {
  if (!_selectedPersonId) return;
  await unlinkPersonContact(_selectedPersonId);
  await _loadAtlas();
  _personDetail = await getPerson(_selectedPersonId, new URLSearchParams({ limit: '30' }));
  uiModule?.showToast?.('Unlinked');
  _render();
}

async function _connectionAction(connectionId, action) {
  await updateConnection(connectionId, action);
  await _loadAtlas();
  if (_selectedPersonId) {
    _personDetail = await getPerson(_selectedPersonId, new URLSearchParams({ limit: '30' }));
  }
  if (action === 'hide' && _editingConnectionId === connectionId) {
    _editingConnectionId = '';
    _connectionDraft = _defaultConnectionDraft();
    _showConnectionForm = false;
  }
  uiModule?.showToast?.(action === 'accept' ? 'Accepted' : 'Hidden');
  _render();
}

export async function openAtlas({ refresh = false, tab = '', personId = '', locationId = '' } = {}) {
  if (Modals.isMinimized(MODAL_ID)) {
    Modals.restore(MODAL_ID);
    _open = true;
  }
  _open = true;
  _error = '';
  if (tab && ['people', 'locations', 'map', 'connections'].includes(tab)) _tab = tab;
  if (personId) {
    _tab = 'people';
    _selectedPersonId = personId;
    _personDetail = null;
  }
  if (locationId) {
    _tab = 'locations';
    _selectedLocationId = locationId;
    _locationDetail = null;
  }
  const modal = _renderShell();
  modal.classList.remove('hidden');
  if (refresh || !_atlas.people?.length && !_atlas.locations?.length) {
    await _loadAtlas();
    _personDetail = null;
    _locationDetail = null;
  }
  if (_tab === 'people' && _selectedPersonId && !_personDetail) {
    _personDetail = await getPerson(_selectedPersonId, new URLSearchParams({ limit: '30' }));
  }
  if (_tab === 'locations' && _selectedLocationId && !_locationDetail) {
    _locationDetail = await getLocation(_selectedLocationId, new URLSearchParams({ limit: '30' }));
  }
  _render();
}

export function closeAtlas() {
  const modal = document.getElementById(MODAL_ID);
  if (modal) {
    _captureWindowRect(modal);
    modal.classList.add('hidden');
  }
  _open = false;
  try { window._restoreSidebarIfRouteCollapsed && window._restoreSidebarIfRouteCollapsed(); } catch (_) {}
}

export function toggleAtlas() {
  if (Modals.toggle(MODAL_ID)) {
    _open = true;
    return;
  }
  if (_open) closeAtlas();
  else openAtlas().catch(_setError);
}

export function isAtlasOpen() {
  return _open;
}

export default {
  openAtlas,
  closeAtlas,
  toggleAtlas,
  isAtlasOpen,
};
