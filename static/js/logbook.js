/**
 * Daily Logbook module.
 */

import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { applyEdgeDock } from './modalSnap.js';
import {
  analyzeEntry,
  assistLogbook,
  createLocation,
  getEntry,
  listConnections,
  listEntries,
  listLocations,
  listPeople,
  saveEntry,
  updateConnection,
} from './logbook/api.js';
import { MODAL_ID, MOODS, QUICK_DATA, SAVE_DELAY } from './logbook/constants.js';
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

function _setStatus(text) {
  _saveStatus = text;
  const el = document.getElementById('logbook-save-status');
  if (el) el.textContent = text;
}

function _markDirty() {
  _dirty = true;
  _setStatus('Unsaved');
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
  if (_saveTimer) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
  }
  _saving = true;
  _setStatus('Saving...');
  try {
    const saved = await saveEntry(_date, _entryPayload());
    _entry = saved;
    _dirty = false;
    _setStatus('Saved');
    await Promise.all([_loadPeople(), _loadLocations(), _loadConnections(), _loadEntries()]);
    _renderPeoplePanel();
    _renderLocationsPanel();
    _renderNavigator();
    if (!silent) uiModule?.showToast?.('Saved');
  } catch (err) {
    _setStatus('Save failed');
    if (!silent) uiModule?.showError?.(err.message || 'Save failed');
    throw err;
  } finally {
    _saving = false;
  }
}

async function _loadEntry(date) {
  _entry = await getEntry(date);
  if (!_entry.datapoints) _entry.datapoints = [];
  if (!_entry.people) _entry.people = [];
  if (!_entry.mentions) _entry.mentions = [];
  if (!_entry.locations) _entry.locations = [];
  if (!_entry.location_mentions) _entry.location_mentions = [];
  _dirty = false;
  _setStatus('Saved');
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
  const data = await listLocations();
  _locations = data.locations || [];
}

async function _loadConnections() {
  const data = await listConnections();
  _connections = data.connections || [];
}

async function _loadDate(date) {
  if (_dirty) {
    try { await _saveNow({ silent: true }); } catch (_) {}
  }
  _date = date;
  _aiPreview = null;
  _aiError = '';
  await Promise.all([_loadEntry(_date), _loadPeople(), _loadLocations(), _loadConnections(), _loadEntries()]);
  _render();
}

function _iconBook(size = 16) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h6M9 11h6M9 15h4"/></svg>`;
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
    skipSelector: 'button, input, select, textarea, label',
    mobileSkip: 980,
    enableDock: true,
    onDragEnd: () => _captureWindowRect(modal),
  });
}

function _render() {
  const modal = _renderShell();
  _captureWindowRect(modal);
  modal.innerHTML = `
    <div class="modal-content logbook-modal-content" role="dialog" aria-label="Daily Logbook">
      <div class="modal-header logbook-modal-header">
        <h4 class="logbook-title">${_iconBook(14)}<span>Logbook</span></h4>
        <div class="logbook-date-controls">
          <button type="button" class="cal-btn" id="logbook-prev-day">Prev</button>
          <input type="date" id="logbook-date-input" value="${_e(_date)}">
          <button type="button" class="cal-btn" id="logbook-next-day">Next</button>
          <button type="button" class="cal-btn" id="logbook-today-btn">Today</button>
        </div>
        <span id="logbook-save-status" class="logbook-save-status">${_e(_saveStatus)}</span>
        <button type="button" class="cal-btn cal-btn-primary" id="logbook-manual-save">Save</button>
        <button type="button" class="close-btn" id="logbook-close" title="Close" aria-label="Close">&#x2716;</button>
      </div>
      <div class="logbook-mobile-tabs">
        ${['write', 'mood', 'data', 'people', 'places', 'ai'].map(tab => `<button type="button" class="logbook-tab ${_activeTab === tab ? 'active' : ''}" data-logbook-tab="${tab}">${tab === 'ai' ? 'AI' : tab[0].toUpperCase() + tab.slice(1)}</button>`).join('')}
      </div>
      <div class="modal-body logbook-body" data-active-tab="${_e(_activeTab)}">
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
      </div>
    </div>
  `;
  Modals.injectMinimizeButton(modal, MODAL_ID);
  _wireLogbookWindow(modal);
  _bindEvents();
  _renderMentionMenu();
}

function _navigatorHtml() {
  const rows = _entries.map(entry => `
    <button type="button" class="logbook-day-row ${entry.entry_date === _date ? 'active' : ''}" data-date="${_e(entry.entry_date)}">
      <span>${_e(_dateLabel(entry.entry_date))}</span>
      <span class="logbook-day-state" data-state="${_e(_entryStatus(entry))}">${_e(_entryStatus(entry))}</span>
    </button>
  `).join('') || '<div class="logbook-empty">No entries in this range.</div>';
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
  return `
    <div class="logbook-editor-head">
      <div>
        <div class="logbook-date-title">${_e(_dateLabel(_date))}</div>
        <div class="logbook-date-sub">${_e(_date)}</div>
      </div>
      <input id="logbook-title-input" class="logbook-title-input" value="${_e(_entry?.title || 'Daily log')}" placeholder="Title">
    </div>
    <section class="logbook-write-section" data-mobile-section="write">
      <textarea id="logbook-content" class="logbook-content" placeholder="Write messy notes. Example: work, training, tired, talked with @Jan. AI can clean it up later.">${_e(_entry?.content || '')}</textarea>
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

function _peopleHtml() {
  const todayPeople = _entry?.people || [];
  const today = todayPeople.length
    ? todayPeople.map(p => `<span class="logbook-person-chip">@${_e(p.display_name)}</span>`).join('')
    : '<div class="logbook-empty">No people mentioned today.</div>';
  const suggestions = (_aiPreview?.people_suggestions || []).map(p => `
    <div class="logbook-suggestion-row">
      <strong>${_e(p.display_name || p.surface_text || 'Person')}</strong>
      <span>${_e(p.reason || 'Suggested from entry')}</span>
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
    return `
      <div class="logbook-directory-row${active}">
        <button type="button" class="logbook-directory-main" data-filter-person="${_e(p.id)}">
          <strong>@${_e(p.display_name)}</strong>
          <span>${_e(meta)}</span>
        </button>
        <button type="button" class="logbook-icon-btn" data-insert-person="${_e(p.display_name)}" aria-label="Insert">+</button>
      </div>
    `;
  }).join('') || '<div class="logbook-empty">No known people yet.</div>';
}

function _locationsHtml() {
  const todayLocations = _entry?.locations || [];
  const today = todayLocations.length
    ? todayLocations.map(l => `<span class="logbook-person-chip">#${_e(l.display_name)}</span>`).join('')
    : '<div class="logbook-empty">No places mentioned today.</div>';
  const suggestions = (_aiPreview?.location_suggestions || []).map(loc => `
    <div class="logbook-suggestion-row">
      <strong>${_e(loc.display_name || loc.surface_text || 'Place')}</strong>
      <span>${_e(loc.reason || 'Suggested from entry')}</span>
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
          <strong>#${_e(loc.display_name)}</strong>
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
    const names = [p.display_name, ...(p.aliases || [])].map(x => String(x || '').toLowerCase());
    return names.some(name => name.includes(term));
  });
  list.sort((a, b) => _directorySort(a, b, _peopleSort));
  return list;
}

function _visibleLocations() {
  const term = _locationSearch.trim().toLowerCase();
  const list = _locations.filter(loc => {
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

function _connectionsHtml() {
  const visible = _connections.filter(c => c.status !== 'hidden');
  const rows = visible.map(conn => {
    const a = conn.person_a?.display_name || 'Person A';
    const b = conn.person_b?.display_name || 'Person B';
    const ev = Array.isArray(conn.evidence) && conn.evidence.length ? conn.evidence[conn.evidence.length - 1] : null;
    const actions = conn.status === 'suggested'
      ? `<div class="logbook-connection-actions"><button type="button" class="cal-btn cal-btn-primary" data-accept-connection="${_e(conn.id)}">Accept</button><button type="button" class="cal-btn" data-hide-connection="${_e(conn.id)}">Hide</button></div>`
      : `<span class="logbook-accepted">Accepted</span>`;
    return `
      <div class="logbook-connection">
        <div class="logbook-connection-title">${_e(a)} + ${_e(b)}</div>
        <div class="logbook-connection-meta">AI noticed a possible ${_e(conn.connection_type || 'connection')} (${_e(conn.confidence || 0)}%)</div>
        ${ev?.snippet ? `<div class="logbook-evidence">${_e(ev.snippet)}</div>` : ''}
        ${actions}
      </div>
    `;
  }).join('');
  return `
    <div class="logbook-section-head"><h5>Connections</h5></div>
    <div id="logbook-connections">${rows || '<div class="logbook-empty">No connection suggestions yet.</div>'}</div>
  `;
}

function _aiHtml() {
  const preview = _aiPreview ? _aiPreviewHtml() : '<div class="logbook-empty">AI previews appear here.</div>';
  return `
    <div class="logbook-section-head"><h5>AI help</h5></div>
    <textarea id="logbook-ai-draft" class="logbook-ai-draft" placeholder="Rough thoughts"></textarea>
    <div class="logbook-ai-buttons">
      <button type="button" class="cal-btn cal-btn-primary" data-ai-mode="structure_day">Help me write today</button>
      <button type="button" class="cal-btn" data-ai-mode="clean_spelling">Clean spelling</button>
      <button type="button" class="cal-btn" data-ai-mode="ask_questions">Ask 3 questions</button>
      <button type="button" class="cal-btn" data-ai-mode="extract_people">Extract people</button>
      <button type="button" class="cal-btn" data-ai-mode="extract_locations">Extract places</button>
      <button type="button" class="cal-btn" data-ai-mode="summarize">Summarize</button>
      <button type="button" class="cal-btn" data-ai-mode="reflect">Reflect</button>
      <button type="button" class="cal-btn" id="logbook-analyze-entry">Analyze saved</button>
    </div>
    ${_aiBusy ? '<div class="logbook-ai-status">Thinking...</div>' : ''}
    ${_aiError ? `<div class="logbook-ai-error">${_e(_aiError)}</div>` : ''}
    <div id="logbook-ai-preview" class="logbook-ai-preview">${preview}</div>
  `;
}

function _aiPreviewHtml() {
  const p = _aiPreview || {};
  const questions = (p.questions || []).map(q => `<li>${_e(q)}</li>`).join('');
  const data = (p.datapoint_suggestions || []).map(d => `
    <div class="logbook-suggestion-row">
      <strong>${_e(d.label || d.key || 'Data')}</strong>
      <span>${_e(d.value_text || d.value_number || '')}${d.unit ? ` ${_e(d.unit)}` : ''}</span>
    </div>
  `).join('');
  const locations = (p.location_suggestions || []).map(loc => `
    <div class="logbook-suggestion-row">
      <strong>${_e(loc.display_name || loc.surface_text || 'Place')}</strong>
      <span>${_e(loc.reason || 'Suggested from entry')}</span>
    </div>
  `).join('');
  const connections = (p.connection_suggestions || []).map(c => `
    <div class="logbook-suggestion-row">
      <strong>${_e(c.person_a || 'Person')} + ${_e(c.person_b || 'Person')}</strong>
      <span>${_e(c.description || c.connection_type || 'Possible connection')}</span>
    </div>
  `).join('');
  return `
    ${p.preview_content ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Preview</div><pre>${_e(p.preview_content)}</pre></div>` : ''}
    ${p.summary ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Summary</div><p>${_e(p.summary)}</p></div>` : ''}
    ${p.reflection ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Reflection</div><p>${_e(p.reflection)}</p></div>` : ''}
    ${questions ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Questions</div><ul>${questions}</ul></div>` : ''}
    ${p.mood_suggestion ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Mood</div><p>${_e(p.mood_suggestion.label || '')} ${p.mood_suggestion.score ? `(${_e(p.mood_suggestion.score)})` : ''}</p><button type="button" class="cal-btn" id="logbook-apply-ai-mood">Use mood</button></div>` : ''}
    ${data ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Data suggestions</div>${data}<button type="button" class="cal-btn" id="logbook-add-ai-data">Add data</button></div>` : ''}
    ${locations ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Place suggestions</div>${locations}</div>` : ''}
    ${connections ? `<div class="logbook-preview-block"><div class="logbook-subtitle">Connection suggestions</div>${connections}</div>` : ''}
    <div class="logbook-preview-actions">
      ${p.preview_content ? '<button type="button" class="cal-btn cal-btn-primary" id="logbook-apply-ai">Apply</button>' : ''}
      <button type="button" class="cal-btn" id="logbook-copy-ai">Copy</button>
      <button type="button" class="cal-btn" id="logbook-clear-ai">Cancel</button>
    </div>
  `;
}

function _bindEvents() {
  document.getElementById('logbook-close')?.addEventListener('click', closeLogbook);
  document.getElementById('logbook-prev-day')?.addEventListener('click', () => _loadDate(_dateAdd(_date, -1)).catch(_showError));
  document.getElementById('logbook-next-day')?.addEventListener('click', () => _loadDate(_dateAdd(_date, 1)).catch(_showError));
  document.getElementById('logbook-today-btn')?.addEventListener('click', () => _loadDate(_today()).catch(_showError));
  document.getElementById('logbook-date-input')?.addEventListener('change', e => _loadDate(e.target.value).catch(_showError));
  document.getElementById('logbook-manual-save')?.addEventListener('click', () => _saveNow().catch(_showError));

  document.querySelectorAll('[data-logbook-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      _activeTab = btn.dataset.logbookTab || 'write';
      _render();
    });
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

  const title = document.getElementById('logbook-title-input');
  title?.addEventListener('input', () => {
    _entry.title = title.value;
    _markDirty();
  });

  const content = document.getElementById('logbook-content');
  content?.addEventListener('input', () => {
    _entry.content = content.value;
    _markDirty();
    _renderMentionMenu();
  });
  content?.addEventListener('keydown', e => {
    if (e.key === 'Escape') _hideMentionMenu();
  });
  content?.addEventListener('click', _renderMentionMenu);
  content?.addEventListener('blur', () => setTimeout(_hideMentionMenu, 180));

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
      _render();
      _markDirty();
    });
  });

  document.querySelectorAll('[data-score-field]').forEach(btn => {
    btn.addEventListener('click', () => {
      const field = btn.dataset.scoreField;
      const score = Number(btn.dataset.score);
      _entry[field] = Number(_entry[field]) === score ? null : score;
      _render();
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
  document.getElementById('logbook-analyze-entry')?.addEventListener('click', () => _analyzeEntry().catch(_showError));
  document.getElementById('logbook-apply-ai')?.addEventListener('click', () => _applyAIContent());
  document.getElementById('logbook-copy-ai')?.addEventListener('click', () => _copyAI());
  document.getElementById('logbook-clear-ai')?.addEventListener('click', () => {
    _aiPreview = null;
    _aiError = '';
    _render();
  });
  document.getElementById('logbook-apply-ai-mood')?.addEventListener('click', () => _applyAIMood());
  document.getElementById('logbook-add-ai-data')?.addEventListener('click', () => _addAIData());
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
  _bindLocationDirectoryEvents();
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
    ? matches.map(p => `<button type="button" data-mention-person="${_e(p.display_name)}">@${_e(p.display_name)}</button>`).join('')
    : matches.map(loc => `<button type="button" data-mention-location="${_e(loc.display_name)}">#${_e(loc.display_name)}</button>`).join('');
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
  return /\s/.test(name) ? `@[${name}]` : `@${name}`;
}

function _locationText(name) {
  return /\s/.test(name) ? `#[${name}]` : `#${name}`;
}

function _replaceMention(ctx, name) {
  const ta = ctx.textarea;
  const text = _mentionText(name);
  ta.value = ta.value.slice(0, ctx.start) + text + ' ' + ta.value.slice(ctx.end);
  const pos = ctx.start + text.length + 1;
  ta.focus();
  ta.setSelectionRange(pos, pos);
  _entry.content = ta.value;
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
  _markDirty();
  _hideMentionMenu();
}

function _insertMention(name) {
  const ta = document.getElementById('logbook-content');
  if (!ta || !name) return;
  const insert = `${ta.value && !/\s$/.test(ta.value) ? ' ' : ''}${_mentionText(name)} `;
  const pos = ta.selectionStart ?? ta.value.length;
  ta.value = ta.value.slice(0, pos) + insert + ta.value.slice(pos);
  const next = pos + insert.length;
  ta.focus();
  ta.setSelectionRange(next, next);
  _entry.content = ta.value;
  _markDirty();
}

function _insertLocation(name) {
  const ta = document.getElementById('logbook-content');
  if (!ta || !name) return;
  const insert = `${ta.value && !/\s$/.test(ta.value) ? ' ' : ''}${_locationText(name)} `;
  const pos = ta.selectionStart ?? ta.value.length;
  ta.value = ta.value.slice(0, pos) + insert + ta.value.slice(pos);
  const next = pos + insert.length;
  ta.focus();
  ta.setSelectionRange(next, next);
  _entry.content = ta.value;
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
  if (_aiBusy) return;
  const draft = document.getElementById('logbook-ai-draft')?.value || '';
  _aiBusy = true;
  _aiError = '';
  _aiPreview = null;
  _render();
  const content = draft.trim()
    ? `${_entry?.content || ''}\n\nExtra thoughts:\n${draft.trim()}`.trim()
    : (_entry?.content || '');
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

async function _analyzeEntry() {
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
    await _loadConnections();
  } catch (err) {
    _aiError = err.message || 'Analyze failed.';
  } finally {
    _aiBusy = false;
    _render();
  }
}

function _applyAIContent() {
  if (!_aiPreview?.preview_content) return;
  const ta = document.getElementById('logbook-content');
  _entry.content = _aiPreview.preview_content;
  if (ta) ta.value = _entry.content;
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
  await _loadConnections();
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

const logbookModule = { openLogbook, closeLogbook, toggleLogbook, isLogbookOpen };
window.logbookModule = logbookModule;
export default logbookModule;
