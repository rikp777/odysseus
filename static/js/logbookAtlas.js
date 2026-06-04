/**
 * Daily Logbook people and places atlas.
 */

import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { applyEdgeDock } from './modalSnap.js';
import { pointsWithCoordinates, pointsWithoutCoordinates, renderCoordinateMap } from './maps.js';
import {
  createLocation,
  createPerson,
  deleteLocation,
  getAtlas,
  getPerson,
  getLocation,
  hideLocation,
  listContactCandidates,
  linkPersonContact,
  unlinkPersonContact,
  unhideLocation,
  updateConnection,
  updateLocation,
  updatePerson,
} from './logbook/api.js';
import { logbookIcon as _logbookIcon } from './logbook/icons.js';
import { escapeHtml as _e } from './logbook/utils.js';

const MODAL_ID = 'logbook-atlas-modal';

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
      const names = [person.display_name, ...(person.aliases || []), person.relationship_label || '']
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

async function _loadAtlas() {
  _atlas = await getAtlas();
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

function _render() {
  const modal = _renderShell();
  _captureWindowRect(modal);
  modal.innerHTML = `
    <div class="modal-content logbook-atlas-content" role="dialog" aria-label="Logbook People and Places">
      <div class="modal-header logbook-atlas-header">
        <h4>People & Places</h4>
        <button type="button" class="close-btn" id="logbook-atlas-close" title="Close" aria-label="Close">&#x2716;</button>
      </div>
      ${_error ? `<div class="logbook-atlas-error">${_e(_error)}</div>` : ''}
      ${_busy ? '<div class="logbook-atlas-status">Saving...</div>' : ''}
      <div class="logbook-atlas-toolbar">
        <div class="logbook-atlas-tabs">
          ${['people', 'locations', 'map', 'connections'].map(tab => `<button type="button" class="logbook-tab ${_tab === tab ? 'active' : ''}" data-atlas-tab="${tab}">${tab === 'map' ? 'Map' : tab[0].toUpperCase() + tab.slice(1)}</button>`).join('')}
        </div>
        <button type="button" class="cal-btn" id="logbook-atlas-refresh">Refresh</button>
      </div>
      <div class="modal-body logbook-atlas-body" data-tab="${_e(_tab)}">
        ${_bodyHtml()}
      </div>
    </div>
  `;
  Modals.injectMinimizeButton(modal, MODAL_ID);
  _wireWindow(modal);
  _bind();
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
      <label>Relation<input id="atlas-person-relation" class="memory-search-input" value="${_e(detail.relationship_label || '')}" placeholder="friend, work, family"></label>
      <label>Notes<textarea id="atlas-person-notes" class="logbook-atlas-text">${_e(detail.notes || '')}</textarea></label>
      <label>LLM context<textarea id="atlas-person-context" class="logbook-atlas-text" placeholder="Context the assistant may use about this person.">${_e(detail.llm_context || '')}</textarea></label>
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
      <label>Address<input id="atlas-location-address" class="memory-search-input" value="${_e(detail.address || '')}"></label>
      <div class="logbook-atlas-coordinates">
        <label>Latitude<input id="atlas-location-lat" class="memory-search-input" type="number" step="any" value="${detail.latitude ?? ''}"></label>
        <label>Longitude<input id="atlas-location-lon" class="memory-search-input" type="number" step="any" value="${detail.longitude ?? ''}"></label>
      </div>
      <label>Notes<textarea id="atlas-location-notes" class="logbook-atlas-text">${_e(detail.notes || '')}</textarea></label>
      <label>LLM context<textarea id="atlas-location-context" class="logbook-atlas-text" placeholder="Context the assistant may use about this place.">${_e(detail.llm_context || '')}</textarea></label>
      <div class="logbook-subtitle">Recent entries</div>
      <div class="logbook-atlas-entry-list">${entries}</div>
    </div>
  `;
}

function _mapTabHtml() {
  const locations = (_atlas.locations || []).filter(location => !location.hidden);
  const points = pointsWithCoordinates(locations);
  const noCoords = pointsWithoutCoordinates(locations);
  const map = renderCoordinateMap(locations, {
    labelKey: 'display_name',
    pinDataAttribute: 'data-map-location',
    emptyText: 'Add latitude and longitude to places to pin them here.',
  });
  return `
    <section class="map-panel">
      <div class="logbook-section-head"><h5>Map</h5><span>${points.length} pinned</span></div>
      ${map}
      <div class="logbook-subtitle">Needs coordinates</div>
      <div class="logbook-atlas-missing">${noCoords.map(location => `<button type="button" class="cal-btn" data-map-location="${_e(location.id)}">${_logbookIcon('location', 12)}${_e(location.display_name)}</button>`).join('') || '<div class="logbook-empty">All places with coordinates are pinned.</div>'}</div>
    </section>
  `;
}

function _connectionsTabHtml() {
  const rows = (_atlas.connections || []).filter(conn => conn.status !== 'hidden').map(conn => {
    const ev = Array.isArray(conn.evidence) && conn.evidence.length ? conn.evidence[conn.evidence.length - 1] : null;
    const actions = conn.status === 'suggested'
      ? `<button type="button" class="cal-btn cal-btn-primary" data-accept-connection="${_e(conn.id)}">Accept</button><button type="button" class="cal-btn" data-hide-connection="${_e(conn.id)}">Hide</button>`
      : '<span class="logbook-accepted">Accepted</span>';
    return `
      <div class="logbook-connection">
        <div class="logbook-connection-title">${_e(conn.person_a?.display_name || 'Person')} + ${_e(conn.person_b?.display_name || 'Person')}</div>
        <div class="logbook-connection-meta">Possible ${_e(conn.connection_type || 'connection')} (${_e(conn.confidence || 0)}%)</div>
        ${conn.description ? `<div class="logbook-evidence">${_e(conn.description)}</div>` : ''}
        ${ev?.snippet ? `<div class="logbook-evidence">${_e(ev.entry_date || '')}: ${_e(ev.snippet)}</div>` : ''}
        <div class="logbook-connection-actions">${actions}</div>
      </div>
    `;
  }).join('');
  return `<section class="logbook-atlas-connections">${rows || '<div class="logbook-empty">No connection suggestions.</div>'}</section>`;
}

function _bind() {
  document.getElementById('logbook-atlas-close')?.addEventListener('click', closeAtlas);
  document.getElementById('logbook-atlas-refresh')?.addEventListener('click', () => openAtlas({ refresh: true }).catch(_setError));
  document.querySelectorAll('[data-atlas-tab]').forEach(btn => {
    btn.addEventListener('click', async () => {
      _tab = btn.dataset.atlasTab || 'people';
      _error = '';
      if (_tab === 'people' && _selectedPersonId && !_personDetail) await _selectPerson(_selectedPersonId);
      else if (_tab === 'locations' && _selectedLocationId && !_locationDetail) await _selectLocation(_selectedLocationId);
      else _render();
    });
  });
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
  document.getElementById('atlas-delete-location')?.addEventListener('click', () => _deleteSelectedLocation().catch(_setError));
  document.getElementById('atlas-hide-location')?.addEventListener('click', () => _hideSelectedLocation().catch(_setError));
  document.getElementById('atlas-unhide-location')?.addEventListener('click', () => _unhideSelectedLocation().catch(_setError));
}

function _bindMap() {
  document.querySelectorAll('[data-map-location]').forEach(btn => {
    btn.addEventListener('click', () => {
      _tab = 'locations';
      _selectLocation(btn.dataset.mapLocation).catch(_setError);
    });
  });
}

function _bindConnections() {
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
    await _loadAtlas();
    _locationDetail = await getLocation(result.location.id, new URLSearchParams({ limit: '30' }));
    uiModule?.showToast?.(result.duplicate ? 'Opened existing place' : 'Saved');
  } finally {
    _busy = false;
    _render();
  }
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
