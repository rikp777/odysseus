const MONTHLY_SPEND_URL = '/api/billing/monthly-spend';
const AUTH_SETTINGS_URL = '/api/auth/settings';
const PROVIDERS_URL = '/api/billing/providers';

export function fetchMonthlySpend(force) {
  const url = force ? `${MONTHLY_SPEND_URL}?refresh=true` : MONTHLY_SPEND_URL;
  return fetch(url, { credentials: 'same-origin' });
}

export async function fetchAuthSettings() {
  const res = await fetch(AUTH_SETTINGS_URL, { credentials: 'same-origin' });
  if (!res.ok) throw new Error('settings unavailable');
  return res.json();
}

export async function fetchBillingProviders() {
  const res = await fetch(PROVIDERS_URL, { credentials: 'same-origin' });
  if (!res.ok) throw new Error('billing providers unavailable');
  const data = await res.json();
  return Array.isArray(data.providers) ? data.providers : [];
}

export async function fetchSessionUsage(sessionId) {
  const id = String(sessionId || '').trim();
  if (!id) return null;
  const res = await fetch(`/api/billing/session/${encodeURIComponent(id)}/usage`, {
    credentials: 'same-origin',
  });
  if (!res.ok) throw new Error('billing session usage unavailable');
  return res.json();
}

export async function saveAuthSettings(payload) {
  const res = await fetch(AUTH_SETTINGS_URL, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('save failed');
  return res.json();
}
