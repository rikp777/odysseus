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

export function listLocations() {
  return jsonFetch(`${API_BASE}/api/logbook/locations`);
}

export function createLocation(displayName) {
  return jsonFetch(`${API_BASE}/api/logbook/locations`, {
    method: 'POST',
    body: JSON.stringify({ display_name: displayName }),
  });
}

export function listConnections() {
  return jsonFetch(`${API_BASE}/api/logbook/connections`);
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

export function updateConnection(connectionId, action) {
  return jsonFetch(`${API_BASE}/api/logbook/connections/${encodeURIComponent(connectionId)}/${action}`, {
    method: 'POST',
  });
}

