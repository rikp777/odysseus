// Custom branch app wiring. Keep Logbook/Billing launchers out of upstream app.js.

import Storage from '../storage.js';
import settingsModule from '../settings.js';
import logbookModule from '../logbook.js';
import logbookAtlasModule from '../logbookAtlas.js';
import { initBillingSpend } from '../billing.js';

const UI_VIS_KEY = 'odysseus-ui-visibility';
const CUSTOM_UI_VIS_MAP = {
  'tool-logbook': '#tool-logbook-btn',
  'tool-logbook-atlas': '#tool-logbook-atlas-btn',
};

let installed = false;

function el(id) {
  return document.getElementById(id);
}

function loadUIVis() {
  return Storage.getJSON(UI_VIS_KEY, {});
}

function applyCustomUIVisibility(state = loadUIVis()) {
  Object.entries(CUSTOM_UI_VIS_MAP).forEach(([key, selector]) => {
    const visible = key in state ? state[key] !== false : true;
    document.querySelectorAll(selector).forEach(node => {
      node.style.display = visible ? '' : 'none';
    });
  });
}

function bindClick(id, handler) {
  const node = el(id);
  if (!node || node.dataset.customAppWired === '1') return;
  node.dataset.customAppWired = '1';
  node.addEventListener('click', handler);
}

function bindLogbookLaunchers() {
  bindClick('tool-logbook-btn', () => {
    logbookModule?.toggleLogbook?.();
  });
  bindClick('tool-logbook-atlas-btn', () => {
    logbookAtlasModule?.toggleAtlas?.();
  });
  bindClick('rail-logbook', () => {
    el('tool-logbook-btn')?.click();
  });
  bindClick('rail-logbook-atlas', () => {
    el('tool-logbook-atlas-btn')?.click();
  });
}

function installCustomRouteOpeners() {
  const openers = {
    '/logbook/atlas': () => logbookAtlasModule?.openAtlas?.(),
    '/logbook': () => logbookModule?.openLogbook?.(),
  };
  const opener = openers[window.location.pathname];
  if (opener) {
    window._odysseusRouteOpener = opener;
  }
}

function installCustomVisibilityHooks() {
  applyCustomUIVisibility();

  document.addEventListener('change', event => {
    const target = event.target;
    const key = target?.dataset?.uiKey;
    if (!key || !(key in CUSTOM_UI_VIS_MAP)) return;
    setTimeout(() => applyCustomUIVisibility(loadUIVis()), 0);
  });

  document.addEventListener('click', event => {
    if (!event.target?.closest?.('#set-uiVisResetBtn')) return;
    setTimeout(() => applyCustomUIVisibility({}), 0);
  });

  window.addEventListener('storage', event => {
    if (event.key === UI_VIS_KEY) applyCustomUIVisibility(loadUIVis());
  });
}

async function initCustomBillingSpend() {
  let isAdmin = false;
  try {
    const res = await fetch('/api/auth/status', { credentials: 'same-origin' });
    if (res.ok) {
      const data = await res.json();
      isAdmin = !!data.is_admin;
    }
  } catch (_) {}

  initBillingSpend({
    isAdmin,
    openSettings: tab => settingsModule.open(tab || 'services'),
  });
}

export function installCustomAppWiring() {
  if (installed) return;
  installed = true;

  bindLogbookLaunchers();
  installCustomRouteOpeners();
  installCustomVisibilityHooks();
  setTimeout(() => {
    initCustomBillingSpend().catch(() => {});
  }, 0);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installCustomAppWiring, { once: true });
} else {
  installCustomAppWiring();
}
