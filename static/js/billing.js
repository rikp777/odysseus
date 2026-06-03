const BILLING_URL = '/api/billing/monthly-spend';

let initialized = false;
let isAdmin = false;
let openSettings = null;
let refreshTimer = null;

function setCostDisplayEnabled(enabled) {
  const on = !!enabled;
  window.__odysseusBillingDisplayEnabled = on;
  document.documentElement.classList.toggle('billing-costs-hidden', !on);
  try {
    window.dispatchEvent(new CustomEvent('odysseus-billing-visibility-changed', { detail: { enabled: on } }));
  } catch (_) {}
}

setCostDisplayEnabled(false);

function el(id) {
  return document.getElementById(id);
}

function clearTimer() {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
}

function hidePill() {
  clearTimer();
  setCostDisplayEnabled(false);
  const pill = el('billing-spend-pill');
  if (pill) pill.classList.add('hidden');
}

function scheduleRefresh(seconds) {
  clearTimer();
  const delay = Math.max(60, Math.min(Number(seconds) || 900, 3600)) * 1000;
  refreshTimer = setTimeout(() => {
    refreshBillingSpend().catch(() => {});
  }, delay);
}

function renderSpend(data) {
  const pill = el('billing-spend-pill');
  const value = el('billing-spend-value');
  const provider = el('billing-spend-provider');
  if (!pill || !value) return;

  setCostDisplayEnabled(isAdmin && data && data.enabled && data.configured);

  if (!isAdmin || !data || !data.enabled || !data.configured) {
    hidePill();
    return;
  }

  pill.classList.remove('hidden', 'billing-warning', 'billing-error');
  if (data.over_warning || data.over_limit) pill.classList.add('billing-warning');
  if (!data.ok) pill.classList.add('billing-error');

  if (provider) provider.textContent = data.provider_short_label || '--';
  value.textContent = data.display || (data.ok ? '--' : 'Error');

  const parts = [];
  if (data.ok) {
    const scope = data.spend_scope === 'model_usage' ? 'model spend' : 'account spend';
    parts.push(`${data.provider_label || 'Cloud'} ${scope}: ${data.display || '--'}`);
    if (data.warning_usd) parts.push(`monthly warning $${data.warning_usd}`);
    if (data.limit_usd) parts.push(`monthly max $${data.limit_usd}`);
    if (data.cached) parts.push('cached');
  } else {
    parts.push(data.error || 'Model spend status unavailable');
  }
  pill.title = parts.join(' - ');
  scheduleRefresh(data.refresh_seconds);
}

export async function refreshBillingSpend(options = {}) {
  if (!isAdmin) {
    hidePill();
    return null;
  }

  const url = options.force ? `${BILLING_URL}?refresh=true` : BILLING_URL;
  try {
    const res = await fetch(url, { credentials: 'same-origin' });
    if (res.status === 403) {
      hidePill();
      return null;
    }
    const data = await res.json();
    renderSpend(data);
    return data;
  } catch (_) {
    renderSpend({
      ok: false,
      enabled: true,
      configured: true,
      error: 'Model spend status unavailable',
      refresh_seconds: 900,
    });
    return null;
  }
}

export function initBillingSpend(options = {}) {
  isAdmin = !!options.isAdmin;
  openSettings = options.openSettings || null;

  const pill = el('billing-spend-pill');
  if (!pill) return;

  if (!initialized) {
    initialized = true;
    pill.addEventListener('click', () => {
      if (typeof openSettings === 'function') {
        openSettings('services');
      } else if (window.settingsModule && typeof window.settingsModule.open === 'function') {
        window.settingsModule.open('services');
      }
    });
    window.addEventListener('odysseus-billing-settings-changed', () => {
      refreshBillingSpend({ force: true }).catch(() => {});
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refreshBillingSpend().catch(() => {});
    });
  }

  if (!isAdmin) {
    hidePill();
    return;
  }

  refreshBillingSpend().catch(() => {});
}
