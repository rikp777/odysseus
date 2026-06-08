function noopHtml() {
  return '';
}

function defaultEscape(value) {
  return String(value ?? '');
}

function defaultIcon() {
  return '';
}

export function directoryMeta(item, aliases = '') {
  const count = Number(item?.mention_count || 0);
  const bits = [];
  bits.push(`${count} ${count === 1 ? 'entry' : 'entries'}`);
  if (item?.last_mentioned) bits.push(`last ${item.last_mentioned}`);
  if (aliases) bits.push(aliases);
  return bits.join(' | ');
}

export function directorySort(a, b, sort) {
  if (sort === 'name') return String(a.display_name || '').localeCompare(String(b.display_name || ''));
  if (sort === 'count') {
    return Number(b.mention_count || 0) - Number(a.mention_count || 0)
      || String(a.display_name || '').localeCompare(String(b.display_name || ''));
  }
  return String(b.last_mentioned || '').localeCompare(String(a.last_mentioned || ''))
    || Number(b.mention_count || 0) - Number(a.mention_count || 0)
    || String(a.display_name || '').localeCompare(String(b.display_name || ''));
}

export function visiblePeople(people = [], { search = '', sort = 'recent' } = {}) {
  const term = String(search || '').trim().toLowerCase();
  const list = (people || []).filter(person => {
    if (!term) return true;
    const factBits = Array.isArray(person.facts)
      ? person.facts.flatMap(fact => [fact?.label, fact?.fact_type, fact?.value_text])
      : [];
    const names = [
      person.display_name,
      ...(person.aliases || []),
      person.relationship_label,
      person.notes,
      person.llm_context,
      ...factBits,
    ].map(value => String(value || '').toLowerCase());
    return names.some(name => name.includes(term));
  });
  list.sort((a, b) => directorySort(a, b, sort));
  return list;
}

export function visibleLocations(locations = [], { search = '', sort = 'recent', includeHidden = false } = {}) {
  const term = String(search || '').trim().toLowerCase();
  const list = (locations || []).filter(location => {
    if (location.hidden && !includeHidden) return false;
    if (!term) return true;
    const names = [location.display_name, ...(location.aliases || [])]
      .map(value => String(value || '').toLowerCase());
    return names.some(name => name.includes(term));
  });
  list.sort((a, b) => directorySort(a, b, sort));
  return list;
}

export function renderPeopleRowsHtml({
  people = [],
  search = '',
  sort = 'recent',
  activePersonId = '',
  escapeHtml = defaultEscape,
  icon = defaultIcon,
  renderFactsPreview = noopHtml,
  renderConnectionsPreview = noopHtml,
} = {}) {
  const e = escapeHtml;
  const rows = visiblePeople(people, { search, sort });
  return rows.map(person => {
    const aliases = (person.aliases || []).slice(0, 3).join(', ');
    const meta = directoryMeta(person, aliases);
    const active = activePersonId === person.id ? ' active' : '';
    return `
      <div class="logbook-directory-row${active}">
        <button type="button" class="logbook-directory-main" data-filter-person="${e(person.id)}">
          <strong>${icon('person', 12)}${e(person.display_name)}</strong>
          <span>${e(meta)}</span>
          ${renderFactsPreview(person, { limit: 2 })}
          ${renderConnectionsPreview(person, { limit: 2, compact: true })}
        </button>
        <button type="button" class="logbook-icon-btn" data-insert-person="${e(person.display_name)}" aria-label="Insert">+</button>
      </div>
    `;
  }).join('') || '<div class="logbook-empty">No known people yet.</div>';
}

export function renderLocationRowsHtml({
  locations = [],
  search = '',
  sort = 'recent',
  activeLocationId = '',
  escapeHtml = defaultEscape,
  icon = defaultIcon,
} = {}) {
  const e = escapeHtml;
  const rows = visibleLocations(locations, { search, sort });
  return rows.map(location => {
    const aliases = (location.aliases || []).slice(0, 3).join(', ');
    const meta = directoryMeta(location, aliases);
    const active = activeLocationId === location.id ? ' active' : '';
    return `
      <div class="logbook-directory-row${active}">
        <button type="button" class="logbook-directory-main" data-filter-location="${e(location.id)}">
          <strong>${icon('location', 12)}${e(location.display_name)}</strong>
          <span>${e(meta)}</span>
        </button>
        <button type="button" class="logbook-icon-btn" data-insert-location="${e(location.display_name)}" aria-label="Insert">+</button>
      </div>
    `;
  }).join('') || '<div class="logbook-empty">No places yet.</div>';
}

export function renderPeoplePanelHtml({
  entry = {},
  aiPreview = {},
  people = [],
  search = '',
  sort = 'recent',
  activePersonId = '',
  escapeHtml = defaultEscape,
  icon = defaultIcon,
  personSuggestionMeta = () => 'Suggested from entry',
  personSuggestionActionLabel = () => 'Add',
  renderFactsPreview = noopHtml,
  renderConnectionsPreview = noopHtml,
} = {}) {
  const e = escapeHtml;
  const todayPeople = entry?.people || [];
  const today = todayPeople.length
    ? todayPeople.map(person => `<span class="logbook-person-chip">${icon('person', 12)}${e(person.display_name)}</span>`).join('')
    : '<div class="logbook-empty">No people mentioned today.</div>';
  const suggestions = (aiPreview?.people_suggestions || []).map((person, index) => `
    <div class="logbook-suggestion-row">
      <strong>${e(person.display_name || person.surface_text || 'Person')}</strong>
      <span>${e(personSuggestionMeta(person))}</span>
      <button type="button" class="cal-btn" data-add-ai-person="${index}">${e(personSuggestionActionLabel(person))}</button>
    </div>
  `).join('');
  return `
    <div class="logbook-section-head"><h5>People</h5></div>
    <div class="logbook-chip-wrap">${today}</div>
    ${suggestions ? `<div class="logbook-subtitle">Suggested people</div>${suggestions}` : ''}
    <div class="logbook-directory-tools">
      <input id="logbook-people-search" class="memory-search-input" placeholder="Find people" value="${e(search)}">
      <select id="logbook-people-sort" class="logbook-select">
        <option value="recent" ${sort === 'recent' ? 'selected' : ''}>Recent</option>
        <option value="count" ${sort === 'count' ? 'selected' : ''}>Most used</option>
        <option value="name" ${sort === 'name' ? 'selected' : ''}>Name</option>
      </select>
    </div>
    <div class="logbook-subtitle">All people</div>
    <div id="logbook-people-list" class="logbook-directory-list">${renderPeopleRowsHtml({
      people,
      search,
      sort,
      activePersonId,
      escapeHtml: e,
      icon,
      renderFactsPreview,
      renderConnectionsPreview,
    })}</div>
  `;
}

export function renderLocationsPanelHtml({
  entry = {},
  aiPreview = {},
  locations = [],
  search = '',
  sort = 'recent',
  activeLocationId = '',
  escapeHtml = defaultEscape,
  icon = defaultIcon,
} = {}) {
  const e = escapeHtml;
  const todayLocations = entry?.locations || [];
  const today = todayLocations.length
    ? todayLocations.map(location => `<span class="logbook-person-chip">${icon('location', 12)}${e(location.display_name)}</span>`).join('')
    : '<div class="logbook-empty">No places mentioned today.</div>';
  const suggestions = (aiPreview?.location_suggestions || []).map((location, index) => `
    <div class="logbook-suggestion-row">
      <strong>${e(location.display_name || location.surface_text || 'Place')}</strong>
      <span>${e(location.reason || 'Suggested from entry')}</span>
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
      <input id="logbook-location-search" class="memory-search-input" placeholder="Find places" value="${e(search)}">
      <select id="logbook-location-sort" class="logbook-select">
        <option value="recent" ${sort === 'recent' ? 'selected' : ''}>Recent</option>
        <option value="count" ${sort === 'count' ? 'selected' : ''}>Most used</option>
        <option value="name" ${sort === 'name' ? 'selected' : ''}>Name</option>
      </select>
    </div>
    <div class="logbook-subtitle">All places</div>
    <div id="logbook-location-list" class="logbook-directory-list">${renderLocationRowsHtml({
      locations,
      search,
      sort,
      activeLocationId,
      escapeHtml: e,
      icon,
    })}</div>
  `;
}

function bindClick(root, selector, handler) {
  root?.querySelectorAll?.(selector)?.forEach(element => {
    element.addEventListener('click', () => handler(element));
  });
}

export function bindDirectoryRowActions(root = globalThis.document, {
  onInsertPerson,
  onFilterPerson,
  onInsertLocation,
  onFilterLocation,
} = {}) {
  if (onInsertPerson) {
    bindClick(root, '[data-insert-person]', element => onInsertPerson(element.dataset.insertPerson));
  }
  if (onFilterPerson) {
    bindClick(root, '[data-filter-person]', element => onFilterPerson(element.dataset.filterPerson || ''));
  }
  if (onInsertLocation) {
    bindClick(root, '[data-insert-location]', element => onInsertLocation(element.dataset.insertLocation));
  }
  if (onFilterLocation) {
    bindClick(root, '[data-filter-location]', element => onFilterLocation(element.dataset.filterLocation || ''));
  }
}

export function bindDirectoryControls({
  documentRef = globalThis.document,
  searchId,
  sortId,
  listId,
  defaultSort = 'recent',
  onSearch,
  onSort,
  renderRows,
  bindRows,
  onCreate,
  createId,
} = {}) {
  function rerenderRows() {
    const list = documentRef?.getElementById?.(listId);
    if (!list || !renderRows) return;
    list.innerHTML = renderRows();
    bindRows?.();
  }

  const search = documentRef?.getElementById?.(searchId);
  search?.addEventListener('input', () => {
    onSearch?.(search.value);
    rerenderRows();
  });

  documentRef?.getElementById?.(sortId)?.addEventListener('change', event => {
    onSort?.(event.target.value || defaultSort);
    rerenderRows();
  });

  if (createId && onCreate) {
    documentRef?.getElementById?.(createId)?.addEventListener('click', onCreate);
  }
}
