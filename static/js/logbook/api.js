const API_BASE = window.location.origin;

async function jsonFetch(url, opts = {}) {
  const res = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const msg = data?.error || data?.detail || `Request failed (${res.status})`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

export function getEntry(date) {
  return jsonFetch(`${API_BASE}/api/logbook/entry/${encodeURIComponent(date)}`);
}

export function saveEntry(date, payload) {
  return jsonFetch(`${API_BASE}/api/logbook/entry/${encodeURIComponent(date)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listEntries(params) {
  return jsonFetch(`${API_BASE}/api/logbook/entries?${params.toString()}`);
}

export function listPeople() {
  return jsonFetch(`${API_BASE}/api/logbook/people`);
}

export function getAtlas(params = new URLSearchParams()) {
  const query = params.toString();
  return jsonFetch(`${API_BASE}/api/logbook/atlas${query ? `?${query}` : ''}`);
}

export function getPerson(personId, params = new URLSearchParams()) {
  const query = params.toString();
  return jsonFetch(`${API_BASE}/api/logbook/people/${encodeURIComponent(personId)}${query ? `?${query}` : ''}`);
}

export function createPerson(payload) {
  return jsonFetch(`${API_BASE}/api/logbook/people`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updatePerson(personId, payload) {
  return jsonFetch(`${API_BASE}/api/logbook/people/${encodeURIComponent(personId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function createPersonFact(personId, payload) {
  return jsonFetch(`${API_BASE}/api/logbook/people/${encodeURIComponent(personId)}/facts`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function mergePeople(payload) {
  return jsonFetch(`${API_BASE}/api/logbook/people/merge`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function linkPersonContact(personId, contactUid) {
  return jsonFetch(`${API_BASE}/api/logbook/people/${encodeURIComponent(personId)}/link-contact`, {
    method: 'POST',
    body: JSON.stringify({ contact_uid: contactUid }),
  });
}

export function unlinkPersonContact(personId) {
  return jsonFetch(`${API_BASE}/api/logbook/people/${encodeURIComponent(personId)}/unlink-contact`, {
    method: 'POST',
  });
}

export function listContactCandidates(q = '') {
  const params = new URLSearchParams();
  if (q.trim()) params.set('q', q.trim());
  return jsonFetch(`${API_BASE}/api/logbook/contacts/candidates?${params.toString()}`);
}

export function listLocations(options = {}) {
  const params = new URLSearchParams();
  if (options.includeHidden) params.set('include_hidden', 'true');
  const query = params.toString();
  return jsonFetch(`${API_BASE}/api/logbook/locations${query ? `?${query}` : ''}`);
}

export function getLocation(locationId, params = new URLSearchParams()) {
  const query = params.toString();
  return jsonFetch(`${API_BASE}/api/logbook/locations/${encodeURIComponent(locationId)}${query ? `?${query}` : ''}`);
}

export function updateLocation(locationId, payload) {
  return jsonFetch(`${API_BASE}/api/logbook/locations/${encodeURIComponent(locationId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function hideLocation(locationId) {
  return jsonFetch(`${API_BASE}/api/logbook/locations/${encodeURIComponent(locationId)}/hide`, {
    method: 'POST',
  });
}

export function unhideLocation(locationId) {
  return jsonFetch(`${API_BASE}/api/logbook/locations/${encodeURIComponent(locationId)}/unhide`, {
    method: 'POST',
  });
}

export function deleteLocation(locationId) {
  return jsonFetch(`${API_BASE}/api/logbook/locations/${encodeURIComponent(locationId)}`, {
    method: 'DELETE',
  });
}

export function createLocation(payload) {
  return jsonFetch(`${API_BASE}/api/logbook/locations`, {
    method: 'POST',
    body: JSON.stringify(typeof payload === 'string' ? { display_name: payload } : payload),
  });
}

export function getMapLocations(withCoordinates = false) {
  const params = new URLSearchParams();
  if (withCoordinates) params.set('with_coordinates', 'true');
  return jsonFetch(`${API_BASE}/api/logbook/map?${params.toString()}`);
}

export function getMapConfig() {
  return jsonFetch(`${API_BASE}/api/logbook/map/config`);
}

export function geocodeAddress(q, limit = 5) {
  const params = new URLSearchParams({ q: String(q || ''), limit: String(limit) });
  return jsonFetch(`${API_BASE}/api/logbook/geocode?${params.toString()}`);
}

export function listConnections() {
  return jsonFetch(`${API_BASE}/api/logbook/connections`);
}

export function createConnection(payload) {
  return jsonFetch(`${API_BASE}/api/logbook/connections`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function saveConnection(connectionId, payload) {
  return jsonFetch(`${API_BASE}/api/logbook/connections/${encodeURIComponent(connectionId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function getAIStatus() {
  return jsonFetch(`${API_BASE}/api/logbook/ai/status`);
}

export function estimateLogbookAI(payload) {
  return jsonFetch(`${API_BASE}/api/logbook/ai/estimate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getLogbookAIUsage() {
  return jsonFetch(`${API_BASE}/api/logbook/ai/usage-summary`);
}

export function assistLogbook(payload) {
  return jsonFetch(`${API_BASE}/api/logbook/ai/assist`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function analyzeEntry(entryId) {
  return jsonFetch(`${API_BASE}/api/logbook/ai/analyze-entry/${encodeURIComponent(entryId)}`, {
    method: 'POST',
  });
}

export function applyEntrySuggestions(entryId, payload) {
  return jsonFetch(`${API_BASE}/api/logbook/entry/${encodeURIComponent(entryId)}/apply-suggestions`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateConnection(connectionId, action) {
  return jsonFetch(`${API_BASE}/api/logbook/connections/${encodeURIComponent(connectionId)}/${action}`, {
    method: 'POST',
  });
}

export function listEntryRevisions(entryId, limit = 20) {
  const params = new URLSearchParams({ limit: String(limit) });
  return jsonFetch(`${API_BASE}/api/logbook/entry/${encodeURIComponent(entryId)}/revisions?${params.toString()}`);
}

export function getEntryRevision(entryId, revisionId) {
  return jsonFetch(`${API_BASE}/api/logbook/entry/${encodeURIComponent(entryId)}/revisions/${encodeURIComponent(revisionId)}`);
}

export function restoreEntryRevision(entryId, revisionId) {
  return jsonFetch(`${API_BASE}/api/logbook/entry/${encodeURIComponent(entryId)}/revisions/${encodeURIComponent(revisionId)}/restore`, {
    method: 'POST',
  });
}
