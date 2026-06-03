#!/usr/bin/env node

import { createReadStream } from 'node:fs';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch (_) {
  chromium = null;
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const docsDir = path.join(repoRoot, 'docs');
const outputDir = path.join(repoRoot, 'output', 'playwright');
const staticDir = path.join(repoRoot, 'static');
const args = new Set(process.argv.slice(2));
const liveDigitalOcean = args.has('--live-digitalocean');
const doToken = process.env.DIGITALOCEAN_BILLING_TOKEN || '';
const onlyViews = new Set(
  process.argv
    .slice(2)
    .filter((arg) => arg.startsWith('--only='))
    .flatMap((arg) => arg.slice('--only='.length).split(',').map((item) => item.trim()).filter(Boolean)),
);

function money(value) {
  const num = Number(value);
  const safe = Number.isFinite(num) ? Math.max(0, num) : 0;
  return '$' + safe.toFixed(2);
}

function compact(value) {
  const num = Math.max(0, Math.round(Number(value) || 0));
  if (num >= 1000000) return `${(num / 1000000).toFixed(num >= 10000000 ? 0 : 1).replace(/\.0$/, '')}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(num >= 10000 ? 0 : 1).replace(/\.0$/, '')}K`;
  return String(num);
}

function isoNow() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

async function fetchDigitalOceanBalance() {
  if (!liveDigitalOcean) return null;
  if (!doToken) {
    throw new Error('Set DIGITALOCEAN_BILLING_TOKEN before using --live-digitalocean.');
  }
  const res = await fetch('https://api.digitalocean.com/v2/customers/my/balance', {
    headers: {
      Authorization: `Bearer ${doToken}`,
      'Content-Type': 'application/json',
    },
  });
  if (!res.ok) {
    throw new Error(`DigitalOcean billing API returned HTTP ${res.status}.`);
  }
  return await res.json();
}

function usage(events, input, output, knownCostEvents = events) {
  return {
    events,
    input_tokens: input,
    output_tokens: output,
    total_tokens: input + output,
    known_cost_events: knownCostEvents,
    unknown_cost_events: Math.max(events - knownCostEvents, 0),
  };
}

function buildCharts(balance) {
  const liveAmount = balance ? Number(balance.month_to_date_usage || 0) : null;
  const total = liveAmount == null ? 12.84 : Math.max(0, liveAmount);
  const updatedAt = balance?.generated_at || isoNow();
  const modelUsage = usage(18, 1480000, 212000, 15);
  const providerUsage = usage(18, 1480000, 212000, 15);
  const digitalOceanAmount = liveAmount == null ? 10.62 : total;
  const localLedgerAmount = liveAmount == null ? 2.22 : Math.min(total, 2.22);

  const base = {
    version: 1,
    kind: 'billing-spend',
    subtitle: liveDigitalOcean ? 'DigitalOcean live month-to-date' : 'June 2026 month-to-date',
    status: 'ok',
    ok: true,
    enabled: true,
    configured: true,
    currency: 'USD',
    total,
    total_display: money(total),
    display: money(total),
    warning: 20,
    warning_display: '$20.00',
    warning_usd: '20.00',
    limit: 35,
    limit_display: '$35.00',
    limit_usd: '35.00',
    projected: total * 1.8,
    projected_display: money(total * 1.8),
    updated_at: updatedAt,
    cached: false,
    provider_label: 'DigitalOcean',
    provider_short_label: 'DO',
    refresh_seconds: 900,
    over_warning: false,
    over_limit: false,
    usage: {
      ...modelUsage,
      enabled: true,
      period: 'month',
      currency: 'USD',
      amount: localLedgerAmount,
      amount_display: money(localLedgerAmount),
      source: 'local_model_usage_ledger',
      source_kind: 'usage_ledger',
      source_label: 'Usage ledger',
    },
    source_note: 'Provider billing totals with usage ledger estimates',
    history: [
      { timestamp: '2026-06-01T08:00:00Z', amount: total * 0.22, display: money(total * 0.22) },
      { timestamp: '2026-06-08T08:00:00Z', amount: total * 0.48, display: money(total * 0.48) },
      { timestamp: '2026-06-15T08:00:00Z', amount: total * 0.72, display: money(total * 0.72) },
      { timestamp: updatedAt, amount: total, display: money(total) },
    ],
    notice: '',
  };

  const model = {
    ...base,
    title: 'Cloud Spend by Model',
    period: 'month',
    group_by: 'model',
    accounts: [
      {
        id: 'gpt-4o',
        account_id: 'gpt-4o',
        label: 'gpt-4o',
        provider: 'local_usage',
        provider_label: 'Local usage',
        amount: 1.48,
        display: '$1.48',
        ok: true,
        usage: usage(11, 960000, 141000, 10),
        source_kind: 'usage_ledger',
        source_label: 'Usage estimate',
      },
      {
        id: 'claude-3-5-sonnet',
        account_id: 'claude-3-5-sonnet',
        label: 'claude-3.5-sonnet',
        provider: 'local_usage',
        provider_label: 'Local usage',
        amount: 0.74,
        display: '$0.74',
        ok: true,
        usage: usage(7, 520000, 71000, 5),
        source_kind: 'usage_ledger',
        source_label: 'Usage estimate',
      },
      {
        id: 'digitalocean-main',
        account_id: 'digitalocean-main',
        label: 'DigitalOcean',
        provider: 'digitalocean',
        provider_label: 'DigitalOcean',
        amount: digitalOceanAmount,
        display: money(digitalOceanAmount),
        ok: true,
        status: 'ok',
        usage: providerUsage,
        source_kind: 'provider_billing',
        source_label: 'Provider billing',
      },
    ],
  };

  const provider = {
    ...base,
    title: 'Cloud Spend by Provider',
    period: 'month',
    group_by: 'provider',
    accounts: [
      {
        id: 'usage-digitalocean',
        account_id: 'usage-digitalocean',
        label: 'digitalocean model usage',
        provider: 'digitalocean',
        provider_label: 'Local usage',
        amount: localLedgerAmount,
        display: money(localLedgerAmount),
        ok: true,
        usage: providerUsage,
        source_kind: 'usage_ledger',
        source_label: 'Usage estimate',
      },
      {
        id: 'digitalocean-main',
        account_id: 'digitalocean-main',
        label: 'DigitalOcean',
        provider: 'digitalocean',
        provider_label: 'DigitalOcean',
        amount: digitalOceanAmount,
        display: money(digitalOceanAmount),
        ok: true,
        status: 'ok',
        usage: {},
        source_kind: 'provider_billing',
        source_label: 'Provider billing',
      },
    ],
  };

  return { model, provider, chat: model };
}

function buildModelItems() {
  return [
    {
      endpoint_id: 'do-inference',
      endpoint_name: 'DigitalOcean',
      category: 'api',
      host: 'digitalocean.com',
      url: 'https://inference.do.example/v1',
      offline: false,
      online: true,
      is_enabled: true,
      models: [
        'openai/gpt-oss-120b',
        'meta-llama/llama-4-maverick',
        'qwen/qwen3-235b-a22b',
      ],
      models_display: [
        'GPT OSS 120B',
        'Llama 4 Maverick',
        'Qwen3 235B A22B',
      ],
      models_extra: [],
      models_extra_display: [],
      model_pricing: {
        'openai/gpt-oss-120b': {
          input_usd_per_unit: 0.15,
          output_usd_per_unit: 0.60,
          unit: '1M tokens',
          source: 'DigitalOcean',
        },
        'meta-llama/llama-4-maverick': {
          input_usd_per_unit: 0.19,
          output_usd_per_unit: 0.78,
          unit: '1M tokens',
          source: 'DigitalOcean',
        },
        'qwen/qwen3-235b-a22b': {
          input_usd_per_unit: 0.12,
          output_usd_per_unit: 0.48,
          unit: '1M tokens',
          source: 'DigitalOcean',
        },
      },
    },
  ];
}

function billingStatus(charts) {
  const model = charts.model;
  return {
    ...model,
    display: model.total_display,
    accounts: [
      {
        account_id: 'digitalocean-main',
        ok: true,
        display: model.accounts.find((item) => item.id === 'digitalocean-main')?.display || model.total_display,
        over_warning: false,
        over_limit: false,
      },
      {
        account_id: 'digitalocean-production',
        ok: true,
        display: '$2.22',
        over_warning: false,
        over_limit: false,
      },
    ],
  };
}

function settingsPayload() {
  return {
    cloud_billing_enabled: true,
    cloud_billing_accounts: [
      {
        id: 'digitalocean-main',
        provider: 'digitalocean',
        label: 'Inference',
        enabled: true,
        api_token_set: true,
      },
      {
        id: 'digitalocean-production',
        provider: 'digitalocean',
        label: 'Production',
        enabled: true,
        api_token_set: true,
      },
    ],
    cloud_billing_refresh_seconds: 900,
    cloud_billing_monthly_warning_usd: '20.00',
    cloud_billing_daily_limit_usd: '1.00',
    cloud_billing_monthly_limit_usd: '35.00',
    cloud_billing_budget_enforcement_enabled: true,
    cloud_billing_usage_ledger_enabled: true,
  };
}

function screenshotData(charts) {
  return {
    charts,
    billingStatus: billingStatus(charts),
    settings: settingsPayload(),
    modelItems: buildModelItems(),
    compactUsage: compact(charts.model.usage.total_tokens),
  };
}

async function appHtml(data) {
  let html = await fs.readFile(path.join(staticDir, 'index.html'), 'utf8');
  html = html
    .replace(/<link id="katex-css"[^>]*>\s*/g, '')
    .replace(/<script async src="https:\/\/cdn\.jsdelivr\.net\/npm\/katex@[^"]+"><\/script>\s*/g, '')
    .replace(/<script id="mermaid-script" async src="https:\/\/cdn\.jsdelivr\.net\/npm\/mermaid@[^"]+"><\/script>\s*/g, '')
    .replace(/<script type="module" src="\/static\/[^"]+"[^>]*><\/script>\s*(?:<!--[^]*?-->\s*)?/g, '')
    .replace(/<script nonce="\{\{CSP_NONCE\}\">if\('serviceWorker'[^]*?<\/script>\s*/g, '');
  const json = JSON.stringify(data).replace(/</g, '\\u003c');
  return html.replace(
    '</body>',
    `<script>window.__billingScreenshotData = ${json};</script>\n<script type="module" src="/billing-screenshot-harness.js"></script>\n</body>`,
  );
}

function harnessJs() {
  return `
import { mdToHtml } from '/static/js/markdown.js';
import { addMessage } from '/static/js/chatRenderer.js';
import { initModelPicker, updateModelPicker } from '/static/js/modelPicker.js';

const data = window.__billingScreenshotData;
const params = new URLSearchParams(window.location.search);
const view = params.get('view') || 'usage-model';
const charts = data.charts;

function $(selector) {
  return document.querySelector(selector);
}

function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function waitFor(predicate, timeoutMs = 5000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    function tick() {
      try {
        if (predicate()) {
          resolve();
          return;
        }
      } catch (_) {}
      if (Date.now() - started > timeoutMs) {
        reject(new Error('Timed out waiting for screenshot state: ' + view));
        return;
      }
      setTimeout(tick, 50);
    }
    tick();
  });
}

function chartBlock(chart) {
  const fence = String.fromCharCode(96, 96, 96);
  return fence + 'billing-chart\\n' + JSON.stringify(chart) + '\\n' + fence;
}

function showAdminUi() {
  window._isAdmin = true;
  window.__odysseusBillingDisplayEnabled = true;
  const loader = document.getElementById('app-loader');
  if (loader) loader.remove();
  document.documentElement.classList.remove('billing-costs-hidden');
  document.querySelectorAll('.admin-only').forEach((node) => {
    node.style.display = '';
  });
}

function fillBillingPill() {
  const pill = $('#billing-spend-pill');
  if (!pill) return;
  pill.classList.remove('hidden', 'billing-warning', 'billing-error');
  const provider = $('#billing-spend-provider');
  const value = $('#billing-spend-value');
  if (provider) provider.textContent = data.billingStatus.provider_short_label || 'DO';
  if (value) value.textContent = data.billingStatus.display || charts.model.total_display;
  pill.title = 'DigitalOcean month-to-date spend: ' + (data.billingStatus.display || charts.model.total_display);
}

function accountStatusState(account, result) {
  if (account && account.enabled === false) return { label: 'Disabled', tone: 'muted' };
  if (account && !account.api_token_set && !(account.api_token || '').trim()) {
    return { label: 'Token missing', tone: 'warning' };
  }
  if (result) {
    if (result.over_limit) return { label: 'Over limit', tone: 'danger' };
    if (result.over_warning) return { label: 'Warning', tone: 'warning' };
    if (result.ok) return { label: 'Connected', tone: 'ok' };
    if (result.status === 'missing_token') return { label: 'Token missing', tone: 'warning' };
    if (result.status === 'unsupported_provider') return { label: 'Unsupported', tone: 'danger' };
    return { label: 'Attention', tone: 'danger' };
  }
  return account && account.api_token_set
    ? { label: 'Saved', tone: 'muted' }
    : { label: 'Unsaved', tone: 'muted' };
}

function accountStatusText(account, result) {
  if (account && account.enabled === false) return 'Excluded from spend total.';
  if (!result) {
    return account && account.api_token_set
      ? 'Saved token; refresh to check spend.'
      : 'Add a billing token, then save.';
  }
  if (result.ok) return (result.display || '--') + ' this month';
  return result.error || result.status || 'Could not refresh billing.';
}

function prepareSidebar() {
  document.documentElement.style.setProperty('--icon-rail-w', '0px');
  document.documentElement.style.setProperty('--sidebar-w', '240px');
  document.body.classList.remove('hamburger-right');

  const iconRail = $('#icon-rail');
  if (iconRail) iconRail.style.display = 'none';

  const sidebar = $('#sidebar');
  if (sidebar) {
    sidebar.classList.remove('hidden', 'right-side');
    sidebar.style.display = 'flex';
    sidebar.style.width = '240px';
  }

  const sessions = $('#sessions-section');
  if (sessions) sessions.style.display = 'none';
  const models = $('#models-section');
  if (models) models.style.display = 'none';

  const userName = $('#user-bar-name');
  if (userName) userName.textContent = 'admin';
  const avatar = $('#user-bar-avatar');
  if (avatar) avatar.textContent = 'A';
}

function fillSettingsCard(options = {}) {
  showAdminUi();
  const modal = $('#settings-modal');
  if (modal) modal.classList.remove('hidden');
  document.querySelectorAll('[data-settings-panel]').forEach((panel) => {
    panel.classList.toggle('hidden', panel.dataset.settingsPanel !== 'services');
  });
  document.querySelectorAll('[data-settings-tab]').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.settingsTab === 'services');
  });

  const settings = data.settings;
  const status = data.billingStatus;
  const card = $('#cloud-billing-card');
  if (!card) throw new Error('Cloud billing card not found');
  card.classList.remove('collapsed', 'billing-unconfigured');
  card.classList.add('billing-configured');

  const toggle = $('#set-cloudBillingToggle');
  if (toggle) toggle.setAttribute('aria-expanded', 'true');
  const summary = $('#set-cloudBillingSummary');
  if (summary) summary.textContent = status.display || charts.model.total_display;

  const setChecked = (selector, checked) => {
    const input = $(selector);
    if (input) input.checked = !!checked;
  };
  setChecked('#set-cloudBillingEnabled', settings.cloud_billing_enabled);
  setChecked('#set-cloudBillingUsageLedger', settings.cloud_billing_usage_ledger_enabled);
  setChecked('#set-cloudBillingBudgetEnforced', settings.cloud_billing_budget_enforcement_enabled);

  const setValue = (selector, value) => {
    const input = $(selector);
    if (input) input.value = value == null ? '' : String(value);
  };
  setValue('#set-cloudBillingRefresh', settings.cloud_billing_refresh_seconds);
  setValue('#set-cloudBillingWarning', settings.cloud_billing_monthly_warning_usd);
  setValue('#set-cloudBillingDailyLimit', settings.cloud_billing_daily_limit_usd);
  setValue('#set-cloudBillingLimit', settings.cloud_billing_monthly_limit_usd);

  const accounts = $('#set-cloudBillingAccounts');
  if (accounts) {
    const results = new Map((status.accounts || []).map((item) => [item.account_id, item]));
    accounts.innerHTML = settings.cloud_billing_accounts.map((account) => (
      (() => {
        const result = results.get(account.id);
        const state = accountStatusState(account, result);
        const warning = state.tone === 'warning' || state.tone === 'danger';
        return (
      '<div class="cloud-billing-account" data-account-id="' + esc(account.id) + '">' +
        '<select class="settings-select" data-field="provider"><option value="digitalocean" selected>DigitalOcean</option></select>' +
        '<input class="settings-input" data-field="label" type="text" placeholder="Label" value="' + esc(account.label || '') + '">' +
        '<input class="settings-input" data-field="api_token" type="password" placeholder="Key stored; enter new key to replace">' +
        '<label class="admin-switch" title="Include this account in the spend total"><input type="checkbox" data-field="enabled" checked><span class="admin-slider"></span></label>' +
        '<button type="button" class="admin-btn-sm" data-action="remove">Remove</button>' +
        '<div class="cloud-billing-account-status' + (warning ? ' billing-warning' : '') + '">' +
          '<span class="cloud-billing-account-badge billing-account-' + state.tone + '">' + esc(state.label) + '</span>' +
          '<span class="cloud-billing-account-status-text">' + esc(accountStatusText(account, result)) + '</span>' +
        '</div>' +
      '</div>'
        );
      })()
    )).join('');
  }

  const addProvider = $('#set-cloudBillingAddProvider');
  if (addProvider) addProvider.value = 'digitalocean';
  const statusEl = $('#set-cloudBillingStatus');
  if (statusEl) {
    statusEl.classList.remove('billing-warning');
    statusEl.textContent = 'DigitalOcean - Current: ' + (status.display || charts.model.total_display) + ' this month - warn at $20.00 - limit $35.00';
  }

  document.body.replaceChildren(card);
  document.body.style.display = 'block';
  document.body.style.height = 'auto';
  document.body.style.overflow = 'visible';
  document.body.style.margin = '0';
  document.body.style.padding = '0';
  document.body.style.background = 'var(--bg)';
  const cardWidth = options.mobile ? '390px' : '560px';
  card.style.width = cardWidth;
  card.style.maxWidth = cardWidth;
  card.style.margin = '0';
}

function renderStandaloneChart(key) {
  showAdminUi();
  fillBillingPill();
  const welcome = $('#welcome-screen');
  if (welcome) welcome.classList.add('hidden');
  const container = $('#chat-container');
  if (container) container.classList.remove('welcome-active');
  const history = $('#chat-history');
  if (!history) throw new Error('Chat history not found');
  history.innerHTML = '';
  const host = document.createElement('div');
  host.innerHTML = mdToHtml(chartBlock(charts[key]));
  history.appendChild(host);
}

function renderChat() {
  showAdminUi();
  prepareSidebar();
  fillBillingPill();
  const container = $('#chat-container');
  if (container) container.classList.remove('welcome-active');
  const welcome = $('#welcome-screen');
  if (welcome) welcome.classList.add('hidden');
  const meta = $('#current-meta');
  if (meta) meta.textContent = 'New Chat';
  const count = $('#current-meta-count');
  if (count) count.textContent = ' - 2 msgs';
  const history = $('#chat-history');
  if (!history) throw new Error('Chat history not found');
  history.innerHTML = '';
  history.classList.add('no-animate');
  addMessage('user', 'show billing usage by model', null, { timestamp: '2026-06-02T15:20:00Z' });
  addMessage(
    'assistant',
    'Here is the spending graph with model usage for this month.\\n\\n' +
      chartBlock(charts.chat),
    'Odysseus',
    { source: 'slash', timestamp: '2026-06-02T15:21:00Z' },
  );
  history.scrollTop = 0;
}

async function renderModelPicker() {
  showAdminUi();
  fillBillingPill();
  const container = $('#chat-container');
  if (container) container.classList.remove('welcome-active');
  const welcome = $('#welcome-screen');
  if (welcome) welcome.classList.add('hidden');

  let pendingChat = {
    url: data.modelItems[0].url,
    modelId: data.modelItems[0].models[0],
    endpointId: data.modelItems[0].endpoint_id,
  };
  window.modelsModule = {
    getCachedItems() {
      return data.modelItems;
    },
    async refreshModels() {
      return null;
    },
  };
  initModelPicker({
    getCurrentSessionId: () => '',
    getSessions: () => [],
    getPendingChat: () => pendingChat,
    setPendingChat: (next) => { pendingChat = next; },
    async createDirectChat(url, modelId, endpointId) {
      pendingChat = { url, modelId, endpointId };
    },
  });
  try {
    window.dispatchEvent(new CustomEvent('odysseus-billing-visibility-changed', { detail: { enabled: true } }));
  } catch (_) {}
  updateModelPicker();
  const btn = $('#model-picker-btn');
  if (!btn) throw new Error('Model picker button not found');
  btn.click();
  await waitFor(() => {
    const menu = $('#model-picker-menu');
    return menu && !menu.classList.contains('hidden') && menu.querySelectorAll('.model-switch-item').length >= 3;
  });
}

async function main() {
  showAdminUi();
  if (view === 'settings' || view === 'settings-mobile') {
    fillSettingsCard({ mobile: view === 'settings-mobile' });
    await waitFor(() => !!$('#cloud-billing-card:not(.collapsed) .cloud-billing-account-status'));
  } else if (view === 'picker') {
    await renderModelPicker();
  } else if (view === 'chat') {
    renderChat();
    await waitFor(() => !!$('.msg-ai .billing-chart-card'));
  } else if (view === 'usage-provider') {
    renderStandaloneChart('provider');
    await waitFor(() => !!$('.billing-chart-card'));
  } else {
    renderStandaloneChart('model');
    await waitFor(() => !!$('.billing-chart-card'));
  }
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  window.__billingScreenshotsReady = true;
}

main().catch((err) => {
  console.error(err);
  window.__billingScreenshotsError = String(err && err.stack || err);
});
`;
}

const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.html': 'text/html; charset=utf-8',
  '.woff2': 'font/woff2',
};

async function sendJson(res, data) {
  res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data));
}

function createServer(data) {
  let cachedHtml = null;
  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url || '/', 'http://127.0.0.1');
      if (url.pathname === '/' || url.pathname === '/billing-screenshots') {
        cachedHtml ||= await appHtml(data);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(cachedHtml);
        return;
      }
      if (url.pathname === '/billing-screenshot-harness.js') {
        res.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' });
        res.end(harnessJs());
        return;
      }
      if (url.pathname === '/api/auth/status') {
        await sendJson(res, { authenticated: true, username: 'admin', is_admin: true });
        return;
      }
      if (url.pathname === '/api/auth/settings') {
        await sendJson(res, data.settings);
        return;
      }
      if (url.pathname === '/api/billing/monthly-spend') {
        await sendJson(res, data.billingStatus);
        return;
      }
      if (url.pathname === '/api/models') {
        await sendJson(res, { items: data.modelItems });
        return;
      }
      if (url.pathname === '/api/model-endpoints/probe-local') {
        await sendJson(res, {});
        return;
      }
      if (url.pathname === '/api/model-endpoints') {
        await sendJson(res, data.modelItems.map((item) => ({
          id: item.endpoint_id,
          name: item.endpoint_name,
          is_enabled: true,
          online: true,
          models: item.models,
        })));
        return;
      }
      if (url.pathname === '/api/default-chat') {
        await sendJson(res, {
          endpoint_url: data.modelItems[0].url,
          endpoint_id: data.modelItems[0].endpoint_id,
          model: data.modelItems[0].models[0],
        });
        return;
      }
      if (url.pathname === '/api/version') {
        await sendJson(res, { version: 'billing-screenshot' });
        return;
      }
      if (url.pathname.startsWith('/api/')) {
        await sendJson(res, {});
        return;
      }
      if (!url.pathname.startsWith('/static/')) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      const relative = decodeURIComponent(url.pathname.replace(/^\/static\//, ''));
      const requested = path.resolve(staticDir, relative);
      const requestedLower = requested.toLowerCase();
      const staticLower = staticDir.toLowerCase();
      if (requestedLower !== staticLower && !requestedLower.startsWith(staticLower + path.sep.toLowerCase())) {
        res.writeHead(403);
        res.end('forbidden');
        return;
      }
      createReadStream(requested)
        .on('error', () => {
          res.writeHead(404);
          res.end('not found');
        })
        .on('open', () => {
          res.writeHead(200, { 'Content-Type': mimeTypes[path.extname(requested)] || 'application/octet-stream' });
        })
        .pipe(res);
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(String(err && err.stack || err));
    }
  });
}

async function launchBrowser() {
  if (!chromium) return null;
  try {
    return await chromium.launch();
  } catch (firstError) {
    try {
      return await chromium.launch({ channel: 'chrome' });
    } catch (_) {
      throw firstError;
    }
  }
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch (_) {
    return false;
  }
}

async function findHeadlessBrowser() {
  const candidates = [
    process.env.BROWSER_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (await exists(candidate)) return candidate;
  }
  return '';
}

function waitForDevTools(child) {
  return new Promise((resolve, reject) => {
    let stderr = '';
    const timeout = setTimeout(() => reject(new Error(`Chrome did not expose DevTools: ${stderr}`)), 15000);
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timeout);
        resolve(match[1]);
      }
    });
    child.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });
    child.on('exit', (code) => {
      if (code) {
        clearTimeout(timeout);
        reject(new Error(`Chrome exited with ${code}: ${stderr}`));
      }
    });
  });
}

async function cdpConnect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
      else resolve(msg);
    }
  });
  return {
    send(method, params = {}) {
      return new Promise((resolve, reject) => {
        const msgId = ++id;
        pending.set(msgId, { resolve, reject });
        ws.send(JSON.stringify({ id: msgId, method, params }));
      });
    },
    close() {
      ws.close();
    },
  };
}

async function waitForReady(client, view) {
  let lastState = null;
  for (let i = 0; i < 100; i += 1) {
    const ready = await client.send('Runtime.evaluate', {
      expression: '({ ready: window.__billingScreenshotsReady === true, error: window.__billingScreenshotsError || "", href: location.href, body: document.body ? document.body.innerText.slice(0, 300) : "" })',
      returnByValue: true,
    });
    lastState = ready.result.result.value;
    if (lastState.ready) return;
    if (lastState.error) throw new Error(lastState.error);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Screenshot page did not become ready for ${view}: ${JSON.stringify(lastState)}`);
}

function clipExpression(selectors) {
  const serialized = JSON.stringify(selectors);
  return `(() => {
    const selectors = ${serialized};
    const rects = selectors.map((selector) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return null;
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    }).filter(Boolean);
    if (!rects.length) return null;
    const left = Math.min(...rects.map((r) => r.left));
    const top = Math.min(...rects.map((r) => r.top));
    const right = Math.max(...rects.map((r) => r.right));
    const bottom = Math.max(...rects.map((r) => r.bottom));
    return {
      x: Math.max(0, Math.floor(left)),
      y: Math.max(0, Math.floor(top)),
      width: Math.ceil(right - left),
      height: Math.ceil(bottom - top),
    };
  })()`;
}

async function clipForPage(page, selectors) {
  return page.evaluate((clipSelectors) => {
    const rects = clipSelectors.map((selector) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return null;
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    }).filter(Boolean);
    if (!rects.length) return null;
    const left = Math.min(...rects.map((r) => r.left));
    const top = Math.min(...rects.map((r) => r.top));
    const right = Math.max(...rects.map((r) => r.right));
    const bottom = Math.max(...rects.map((r) => r.bottom));
    return {
      x: Math.max(0, Math.floor(left)),
      y: Math.max(0, Math.floor(top)),
      width: Math.ceil(right - left),
      height: Math.ceil(bottom - top),
    };
  }, selectors);
}

async function captureWithCdp(browserPath, capture, url) {
  const userDataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'odysseus-billing-shot-'));
  const child = spawn(browserPath, [
    '--headless=new',
    '--disable-gpu',
    '--disable-crash-reporter',
    '--disable-crashpad',
    '--hide-scrollbars',
    '--no-first-run',
    '--remote-debugging-port=0',
    `--user-data-dir=${userDataDir}`,
    `--window-size=${capture.width},${capture.height}`,
    url,
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
  let client;
  try {
    const browserWs = await waitForDevTools(child);
    const httpBase = browserWs.replace(/^ws:/, 'http:').replace(/\/devtools\/browser\/.*$/, '');
    const targets = await (await fetch(`${httpBase}/json/list`)).json();
    const target = targets.find((item) => item.type === 'page' && String(item.url || '').includes('/billing-screenshots'))
      || targets.find((item) => item.type === 'page')
      || targets[0];
    client = await cdpConnect(target.webSocketDebuggerUrl);
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await waitForReady(client, capture.view);
    await new Promise((resolve) => setTimeout(resolve, 350));

    let clip;
    if (capture.selector || capture.selectors) {
      const selectors = capture.selectors || [capture.selector];
      const result = await client.send('Runtime.evaluate', {
        expression: clipExpression(selectors),
        returnByValue: true,
      });
      const box = result.result.result.value;
      if (!box) throw new Error(`Selector not found: ${selectors.join(', ')}`);
      clip = { ...box, scale: 1 };
    } else {
      clip = { x: 0, y: 0, width: capture.width, height: capture.height, scale: 1 };
    }
    const shot = await client.send('Page.captureScreenshot', { format: 'png', fromSurface: true, clip });
    await fs.writeFile(capture.path, Buffer.from(shot.result.data, 'base64'));
  } finally {
    if (client) client.close();
    child.kill();
    await waitForExit(child, 2500);
    await rmRetry(userDataDir);
  }
}

async function waitForExit(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    child.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function rmRetry(target) {
  for (let i = 0; i < 8; i += 1) {
    try {
      await fs.rm(target, { recursive: true, force: true });
      return;
    } catch (err) {
      if (err?.code !== 'EBUSY' && err?.code !== 'EPERM') throw err;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
}

function capturePlan() {
  const dir = liveDigitalOcean ? outputDir : docsDir;
  const prefix = liveDigitalOcean ? 'pr-518-billing-live-digitalocean' : 'pr-518-billing';
  const plan = [
    {
      view: 'settings',
      path: path.join(dir, `${prefix}-settings-card.png`),
      selector: '#cloud-billing-card',
      width: 980,
      height: 850,
    },
    {
      view: 'settings-mobile',
      path: path.join(dir, `${prefix}-settings-mobile.png`),
      selector: '#cloud-billing-card',
      width: 390,
      height: 1180,
    },
    {
      view: 'picker',
      path: path.join(dir, `${prefix}-model-picker-menu.png`),
      selector: '#model-picker-menu',
      width: 1120,
      height: 900,
    },
    {
      view: 'chat',
      path: path.join(dir, `${prefix}-chat-graph.png`),
      selectors: ['#sidebar', '#chat-container'],
      width: 1120,
      height: 1000,
    },
    {
      view: 'usage-model',
      path: path.join(dir, `${prefix}-usage-model.png`),
      selector: '.billing-chart-card',
      width: 1120,
      height: 900,
    },
    {
      view: 'usage-provider',
      path: path.join(dir, `${prefix}-usage-provider.png`),
      selector: '.billing-chart-card',
      width: 1120,
      height: 900,
    },
  ];
  return onlyViews.size ? plan.filter((capture) => onlyViews.has(capture.view)) : plan;
}

async function captureAll(urlBase, captures) {
  const browser = await launchBrowser();
  if (browser) {
    try {
      for (const capture of captures) {
        const page = await browser.newPage({
          viewport: { width: capture.width, height: capture.height },
          deviceScaleFactor: 1,
        });
        await page.goto(`${urlBase}?view=${encodeURIComponent(capture.view)}`, { waitUntil: 'networkidle' });
        await page.waitForFunction(() => window.__billingScreenshotsReady === true);
        if (capture.selectors) {
          const clip = await clipForPage(page, capture.selectors);
          if (!clip) throw new Error(`Selector not found: ${capture.selectors.join(', ')}`);
          await page.screenshot({ path: capture.path, clip });
        } else if (capture.selector) {
          await page.locator(capture.selector).screenshot({ path: capture.path });
        } else {
          await page.screenshot({ path: capture.path, fullPage: false });
        }
        await page.close();
      }
    } finally {
      await browser.close();
    }
    return;
  }

  const browserPath = await findHeadlessBrowser();
  if (!browserPath) {
    throw new Error('No Playwright package or headless Chrome/Edge browser found. Install Playwright or set BROWSER_PATH.');
  }
  for (const capture of captures) {
    const url = `${urlBase}?view=${encodeURIComponent(capture.view)}`;
    await captureWithCdp(browserPath, capture, url);
  }
}

await fs.mkdir(docsDir, { recursive: true });
await fs.mkdir(outputDir, { recursive: true });

const balance = await fetchDigitalOceanBalance();
const charts = buildCharts(balance);
const data = screenshotData(charts);
const server = createServer(data);

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
const urlBase = `http://127.0.0.1:${port}/billing-screenshots`;
const captures = capturePlan();

try {
  await captureAll(urlBase, captures);
  if (balance) {
    console.log(`DigitalOcean billing API OK. month_to_date_usage=${money(balance.month_to_date_usage || 0)}`);
  }
  for (const capture of captures) {
    console.log(`Saved ${capture.path}`);
  }
} finally {
  server.close();
}
