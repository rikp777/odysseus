// static/js/billing/settings.js - Cloud billing settings panel controller

import uiModule from '../ui.js';
import {
  normalizeProviderCatalog,
  providerHint,
  providerLabel,
  providerOptions,
} from './providers.js';
import { fetchAuthSettings, fetchBillingProviders, fetchMonthlySpend, saveAuthSettings } from './api.js';

function el(id) { return document.getElementById(id); }
function esc(s) { return uiModule.esc(s); }

/* ── Cloud Billing (Services tab) ── */
export async function initCloudBillingSettings() {
  var enabledToggle = el('set-cloudBillingEnabled');
  if (!enabledToggle) return;

  var card = el('cloud-billing-card');
  var usageLedgerToggle = el('set-cloudBillingUsageLedger');
  var budgetEnforcedToggle = el('set-cloudBillingBudgetEnforced');
  var toggleBtn = el('set-cloudBillingToggle');
  var summaryEl = el('set-cloudBillingSummary');
  var currentSpendEl = el('set-cloudBillingCurrentSpend');
  var auditEl = el('set-cloudBillingAudit');
  var auditSummaryEl = el('set-cloudBillingAuditSummary');
  var eventsEl = el('set-cloudBillingEvents');
  var eventsSummaryEl = el('set-cloudBillingEventsSummary');
  var refreshSelect = el('set-cloudBillingRefresh');
  var dailyWarningToggle = el('set-cloudBillingDailyWarningToggle');
  var dailyWarningInput = el('set-cloudBillingDailyWarning');
  var warningToggle = el('set-cloudBillingWarningToggle');
  var warningInput = el('set-cloudBillingWarning');
  var dailyLimitToggle = el('set-cloudBillingDailyLimitToggle');
  var dailyLimitInput = el('set-cloudBillingDailyLimit');
  var limitToggle = el('set-cloudBillingLimitToggle');
  var limitInput = el('set-cloudBillingLimit');
  var accountsEl = el('set-cloudBillingAccounts');
  var addProvider = el('set-cloudBillingAddProvider');
  var addLabel = el('set-cloudBillingAddLabel');
  var addToken = el('set-cloudBillingAddToken');
  var addBtn = el('set-cloudBillingAdd');
  var saveBtn = el('set-cloudBillingSave');
  var refreshBtn = el('set-cloudBillingRefreshNow');
  var msg = el('set-cloudBillingMsg');
  var status = el('set-cloudBillingStatus');
  var currentSettings = {};
  var accounts = [];
  var providerCatalog = [];
  var thresholdControls = [
    { toggle: dailyWarningToggle, input: dailyWarningInput },
    { toggle: dailyLimitToggle, input: dailyLimitInput },
    { toggle: warningToggle, input: warningInput },
    { toggle: limitToggle, input: limitInput },
  ];

  function setCollapsed(collapsed) {
    if (!card) return;
    card.classList.toggle('collapsed', !!collapsed);
    if (toggleBtn) toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  function hasConfiguredAccount() {
    if (usageLedgerToggle && usageLedgerToggle.checked) return true;
    return accounts.some(function(account) {
      return !!(account && (account.api_token_set || (account.api_token || '').trim()));
    });
  }

  function setDisabled(node, disabled) {
    if (node) node.disabled = !!disabled;
  }

  function thresholdValue(input, toggle) {
    if (!input) return '';
    if (toggle && !toggle.checked) return '';
    return (input.value || '').trim();
  }

  function thresholdInputHasValue(input) {
    return !!(input && (input.value || '').trim());
  }

  function focusThresholdInput(input) {
    if (!input) return;
    setTimeout(function() {
      input.focus();
      input.select();
    }, 0);
  }

  function syncThresholdControl(input, toggle, disabled) {
    if (!input) return;
    var active = !!(toggle && toggle.checked);
    input.disabled = !!disabled || !active;
    input.closest('.cloud-billing-budget-cell')?.classList.toggle('budget-disabled', !active || !!disabled);
  }

  function syncThresholdControls(disabled) {
    thresholdControls.forEach(function(control) {
      syncThresholdControl(control.input, control.toggle, disabled);
    });
  }

  function applyThreshold(input, toggle, value) {
    var normalized = value == null ? '' : String(value);
    if (input) input.value = normalized;
    if (toggle) toggle.checked = normalized.trim() !== '';
  }

  function currentSpendHtml(amount, meta, chips) {
    var chipHtml = (chips || []).filter(Boolean).map(function(chip) {
      return '<span>' + esc(chip) + '</span>';
    }).join('');
    return '<div class="cloud-billing-current-main">' +
        '<div><span>Current AI Spend</span><strong>' + esc(amount || '--') + '</strong></div>' +
        '<span class="cloud-billing-current-period">Month to date</span>' +
      '</div>' +
      '<div class="cloud-billing-current-meta">' + esc(meta || '') + '</div>' +
      (chipHtml ? '<div class="cloud-billing-current-chips">' + chipHtml + '</div>' : '');
  }

  function localUsageDisplay(statusData) {
    var usage = statusData && statusData.local_usage;
    if (!usage || usage.enabled === false) return '';
    return usage.amount_display || usage.display || '';
  }

  function auditItem(label, value, meta) {
    return '<div class="cloud-billing-audit-item">' +
      '<span>' + esc(label) + '</span>' +
      '<strong>' + esc(value || '--') + '</strong>' +
      (meta ? '<span>' + esc(meta) + '</span>' : '') +
    '</div>';
  }

  function accountHealthTone(row) {
    if (!row || row.enabled === false) return 'muted';
    if (!row.configured) return 'warning';
    if (!row.ok) return 'danger';
    return 'ok';
  }

  function accountHealthMeta(row) {
    if (!row) return '';
    if (row.last_error) return row.last_error;
    var parts = [];
    if (row.last_success_at) parts.push('Success ' + row.last_success_at);
    else if (row.last_checked_at) parts.push('Checked ' + row.last_checked_at);
    if (row.cached && row.cache_age_seconds) parts.push('cached ' + row.cache_age_seconds + 's');
    return parts.join(' · ');
  }

  function renderDiagnostics(statusData) {
    if (!auditEl) return;
    var audit = statusData && statusData.spend_audit;
    var health = statusData && Array.isArray(statusData.provider_health) ? statusData.provider_health : [];
    if (!audit) {
      auditEl.innerHTML = '<div class="admin-empty">No billing data yet.</div>';
      if (auditSummaryEl) auditSummaryEl.textContent = 'No data';
      return;
    }

    var providerModel = audit.provider_model_billing || {};
    var providerAccount = audit.provider_account_total || {};
    var localUsage = audit.local_usage || {};
    var healthSummary = audit.provider_health || {};
    var selectedSource = audit.selected_source || statusData.source_label || statusData.spend_source || '';
    var summaryParts = [];
    if (audit.model_spend_display) summaryParts.push(audit.model_spend_display);
    if (selectedSource) summaryParts.push(selectedSource);
    if (auditSummaryEl) auditSummaryEl.textContent = summaryParts.join(' · ') || 'Audit';

    var healthHtml = health.length ? health.map(function(row) {
      var tone = accountHealthTone(row);
      var chips = [
        '<span class="cloud-billing-account-badge billing-account-' + tone + '">' + esc(row.status_label || row.status || 'Status') + '</span>',
        '<span class="cloud-billing-health-chip">' + esc(row.can_read_model_usage ? 'Model billing' : 'No model billing') + '</span>',
        '<span class="cloud-billing-health-chip">' + esc(row.can_read_account_total ? 'Account total' : 'No account total') + '</span>',
      ].join('');
      return '<div class="cloud-billing-health-row">' +
        '<div class="cloud-billing-health-main">' +
          '<strong>' + esc(row.account_label || row.provider_label || 'Provider') + '</strong>' +
          '<span>' + esc(accountHealthMeta(row)) + '</span>' +
        '</div>' +
        '<div class="cloud-billing-health-chips">' + chips + '</div>' +
      '</div>';
    }).join('') : '<div class="admin-empty">No provider accounts configured.</div>';

    auditEl.innerHTML =
      '<div class="cloud-billing-audit-grid">' +
        auditItem('Current AI spend', audit.model_spend_display || '', selectedSource || 'No model spend source') +
        auditItem('Provider model billing', providerModel.display || '', providerModel.available ? providerModel.accounts + ' account(s)' : 'Unavailable') +
        auditItem('Usage ledger', localUsage.display || '', (localUsage.events || 0) + ' events · ' + (localUsage.unknown_cost_events || 0) + ' unpriced') +
        auditItem('Provider account total', providerAccount.display || '', providerAccount.available ? 'All services' : 'Unavailable') +
        auditItem('Provider health', (healthSummary.connected || 0) + '/' + (healthSummary.accounts || 0) + ' connected', (healthSummary.errors || 0) + ' error(s)') +
        auditItem('Last refresh', audit.last_refreshed_at || '', audit.cached ? 'Cached ' + (audit.cache_age_seconds || 0) + 's' : 'Live') +
      '</div>' +
      '<div class="cloud-billing-health-list">' + healthHtml + '</div>';
  }

  function eventSeverity(row) {
    var severity = row && row.severity ? String(row.severity).toLowerCase() : 'info';
    return ['info', 'warning', 'danger'].indexOf(severity) >= 0 ? severity : 'info';
  }

  function budgetStateMeta(state) {
    if (!state) return '';
    var parts = [];
    if (state.source_label) parts.push(state.source_label);
    if (state.limit_display) parts.push('max ' + state.limit_display);
    if (state.warning_display) parts.push('warning ' + state.warning_display);
    if (state.enforcement_enabled === false) parts.push('enforcement off');
    return parts.join(' · ');
  }

  function renderBudgetActivity(statusData) {
    if (!eventsEl) return;
    var state = statusData && statusData.budget_state ? statusData.budget_state : null;
    var events = statusData && Array.isArray(statusData.budget_events) ? statusData.budget_events : [];
    var summary = 'No events';
    if (state && state.block_remote_models) summary = 'Remote models blocked';
    else if (state && state.over_warning) summary = 'Warning reached';
    else if (events.length) summary = events.length + ' recent event' + (events.length === 1 ? '' : 's');
    if (eventsSummaryEl) eventsSummaryEl.textContent = summary;

    var stateClass = state && state.block_remote_models
      ? 'danger'
      : (state && state.over_warning ? 'warning' : 'info');
    var stateTitle = state && state.block_remote_models
      ? 'Remote model calls are blocked'
      : (state && state.over_warning ? 'Budget warning reached' : 'Budgets are active');
    var stateMessage = state && state.block_reason
      ? state.block_reason
      : (state && state.configured ? 'Remote model calls are allowed under the current budget settings.' : 'Configure billing to track budget activity.');
    var stateHtml = '<div class="cloud-billing-budget-state billing-event-' + stateClass + '">' +
      '<strong>' + esc(stateTitle) + '</strong>' +
      '<span>' + esc(stateMessage) + '</span>' +
      '<small>' + esc(budgetStateMeta(state)) + '</small>' +
    '</div>';

    var rowsHtml = events.length ? events.map(function(row) {
      var severity = eventSeverity(row);
      var repeated = row.count && row.count > 1 ? ' · x' + row.count : '';
      var timestamp = row.last_seen_at || row.created_at || '';
      return '<div class="cloud-billing-event-row billing-event-' + severity + '">' +
        '<span class="cloud-billing-event-dot"></span>' +
        '<div class="cloud-billing-event-copy">' +
          '<strong>' + esc(row.title || row.kind || 'Billing event') + '</strong>' +
          '<span>' + esc(row.message || '') + '</span>' +
          '<small>' + esc([timestamp, row.source || '', repeated.replace(/^ · /, '')].filter(Boolean).join(' · ')) + '</small>' +
        '</div>' +
      '</div>';
    }).join('') : '<div class="admin-empty">No budget activity yet.</div>';

    eventsEl.innerHTML = stateHtml + '<div class="cloud-billing-event-list">' + rowsHtml + '</div>';
  }

  function currentSpendChips(statusData, fallbackSource) {
    var chips = [];
    var source = statusData && statusData.source_label ? statusData.source_label : fallbackSource;
    if (source) chips.push(source);
    if (statusData && statusData.budget_state && statusData.budget_state.block_remote_models) {
      chips.push('Remote models blocked');
    }
    if (statusData && statusData.limit_usd) chips.push('Monthly max $' + statusData.limit_usd);
    else if (statusData && statusData.warning_usd) chips.push('Monthly warning $' + statusData.warning_usd);
    if (statusData && statusData.provider_display) {
      chips.push('Provider account total ' + statusData.provider_display + ' (all services)');
    }
    return chips;
  }

  function renderCurrentSpend(statusData) {
    if (!currentSpendEl) return;
    currentSpendEl.className = 'cloud-billing-current';
    if (!statusData) {
      currentSpendEl.classList.add('is-loading');
      currentSpendEl.innerHTML = currentSpendHtml('--', 'Refresh billing to show model usage.', []);
      return;
    }

    var ledgerDisplay = localUsageDisplay(statusData);
    if (statusData.ok && statusData.spend_scope === 'model_usage') {
      if (statusData.over_warning || statusData.over_limit) currentSpendEl.classList.add('billing-warning');
      currentSpendEl.innerHTML = currentSpendHtml(
        statusData.display || '$0.00',
        'AI/model usage this month. This value drives graphs, warnings, and max usage.',
        currentSpendChips(statusData, '')
      );
      return;
    }

    if (ledgerDisplay) {
      currentSpendEl.classList.add('is-muted');
      currentSpendEl.innerHTML = currentSpendHtml(
        ledgerDisplay,
        statusData.enabled === false
          ? 'Spend display is disabled, but the usage ledger still has current AI/model usage.'
          : 'AI/model usage from the local usage ledger.',
        currentSpendChips(statusData, 'Usage ledger')
      );
      return;
    }

    if (statusData.enabled === false) {
      currentSpendEl.classList.add('is-muted');
      currentSpendEl.innerHTML = currentSpendHtml('--', 'Model spend display is disabled.', []);
      return;
    }
    if (!statusData.configured) {
      currentSpendEl.classList.add('is-muted');
      currentSpendEl.innerHTML = currentSpendHtml('--', 'Enable the usage ledger or add a provider account to show AI spend.', []);
      return;
    }
    if (!statusData.ok) {
      currentSpendEl.classList.add('billing-warning');
      currentSpendEl.innerHTML = currentSpendHtml('--', statusData.error || 'Model spend status unavailable.', []);
      return;
    }

    currentSpendEl.classList.add('is-muted');
    currentSpendEl.innerHTML = currentSpendHtml(
      '--',
      'AI/model spend is not available from this provider response; only account-level billing is available.',
      currentSpendChips(statusData, '')
    );
  }

  function syncBillingAvailability(statusData) {
    var configured = statusData && typeof statusData.configured === 'boolean'
      ? !!statusData.configured
      : hasConfiguredAccount();
    if (card) {
      card.classList.toggle('billing-configured', configured);
      card.classList.toggle('billing-unconfigured', !configured);
    }

    setDisabled(enabledToggle, !configured);
    setDisabled(budgetEnforcedToggle, !configured);
    setDisabled(refreshSelect, !configured);
    setDisabled(dailyWarningToggle, !configured);
    setDisabled(dailyLimitToggle, !configured);
    setDisabled(warningToggle, !configured);
    setDisabled(limitToggle, !configured);
    syncThresholdControls(!configured);
    setDisabled(refreshBtn, !configured);
    if (!configured) enabledToggle.checked = false;

    if (summaryEl) {
      if (!configured) summaryEl.textContent = 'Optional';
      else if (statusData && statusData.ok && statusData.display) summaryEl.textContent = statusData.display;
      else if (statusData && statusData.enabled === false) summaryEl.textContent = 'Configured';
      else if (statusData && statusData.error) summaryEl.textContent = 'Needs attention';
      else summaryEl.textContent = 'Configured';
    }
    renderCurrentSpend(statusData || (configured ? null : { enabled: false, configured: false }));
    renderDiagnostics(statusData || (configured ? null : { enabled: false, configured: false }));
    renderBudgetActivity(statusData || (configured ? null : { enabled: false, configured: false }));
  }

  function setMsg(text, isError) {
    if (!msg) return;
    msg.textContent = text || '';
    msg.style.color = isError ? 'var(--red)' : 'var(--fg)';
  }

  function setStatus(text, isWarning) {
    if (!status) return;
    status.textContent = text || '';
    status.classList.toggle('billing-warning', !!isWarning);
  }

  function populateAddProviderOptions() {
    if (!addProvider) return;
    var selected = addProvider.value;
    addProvider.innerHTML = providerOptions(providerCatalog, selected, esc, []);
    if (providerCatalog.length) {
      addProvider.disabled = false;
      if (selected && Array.from(addProvider.options).some(function(opt) { return opt.value === selected; })) {
        addProvider.value = selected;
      }
      if (!addProvider.value) addProvider.value = providerCatalog[0].id;
      return;
    }
    addProvider.disabled = true;
    var opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Providers unavailable';
    addProvider.appendChild(opt);
  }

  async function loadProviderCatalog() {
    try {
      providerCatalog = normalizeProviderCatalog(await fetchBillingProviders());
    } catch (e) {
      providerCatalog = [];
    }
    populateAddProviderOptions();
  }

  function normalizeAccounts(raw) {
    if (!Array.isArray(raw)) return [];
    return raw.filter(function(account) { return account && typeof account === 'object'; }).map(function(account, idx) {
      var provider = account.provider || 'digitalocean';
      return {
        id: account.id || ('acct-' + Date.now().toString(36) + '-' + idx),
        provider: provider,
        label: account.label || '',
        enabled: account.enabled !== false,
        api_token_set: !!account.api_token_set,
        api_token: account.api_token || '',
      };
    });
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
        ? 'Saved token; refresh to check account billing.'
        : 'Add a billing token, then save.';
    }
    if (result.ok && result.model_display && result.amount_scope === 'provider_account') {
      return 'Model usage: ' + result.model_display + '; account total: ' + (result.display || '--') + ' this month (all services).';
    }
    if (result.ok && result.amount_scope === 'model_usage') {
      return 'Provider model usage: ' + (result.model_display || result.display || '--') + ' this month.';
    }
    if (result.ok) return 'Provider account total: ' + (result.display || '--') + ' this month (all services, not AI-only).';
    return result.error || result.status || 'Could not refresh billing.';
  }

  function renderAccounts(statusData) {
    if (!accountsEl) return;
    var results = {};
    if (statusData && Array.isArray(statusData.accounts)) {
      statusData.accounts.forEach(function(item) { results[item.account_id] = item; });
    }
    if (!accounts.length) {
      accountsEl.innerHTML = '<div class="admin-empty">No cloud billing accounts yet.</div>';
      syncBillingAvailability(statusData);
      return;
    }
    accountsEl.innerHTML = accounts.map(function(account) {
      var result = results[account.id];
      var state = accountStatusState(account, result);
      var resultWarning = state.tone === 'warning' || state.tone === 'danger';
      var tokenPlaceholder = account.api_token_set ? 'Key stored; enter new key to replace' : providerHint(providerCatalog, account.provider);
      var label = providerLabel(providerCatalog, account.provider);
      var accountTitle = account.label || label;
      return '<div class="cloud-billing-account" data-account-id="' + esc(account.id) + '">' +
        '<div class="cloud-billing-account-head">' +
          '<div class="cloud-billing-account-title">' +
            '<strong>' + esc(accountTitle) + '</strong>' +
            '<span>' + esc(label) + '</span>' +
          '</div>' +
          '<div class="cloud-billing-account-actions">' +
            '<span class="cloud-billing-include-toggle" title="Include this account in provider billing checks"><span>Include</span><label class="admin-switch"><input type="checkbox" data-field="enabled" ' + (account.enabled ? 'checked' : '') + '><span class="admin-slider"></span></label></span>' +
            '<button type="button" class="admin-btn-sm cloud-billing-test" data-action="test">Test</button>' +
            '<button type="button" class="admin-btn-sm cloud-billing-remove" data-action="remove">Remove</button>' +
          '</div>' +
        '</div>' +
        '<div class="cloud-billing-account-status' + (resultWarning ? ' billing-warning' : '') + '">' +
          '<span class="cloud-billing-account-badge billing-account-' + state.tone + '">' + esc(state.label) + '</span>' +
          '<span class="cloud-billing-account-status-text">' + esc(accountStatusText(account, result)) + '</span>' +
        '</div>' +
        '<div class="cloud-billing-account-fields">' +
          '<label class="cloud-billing-field"><span>Provider</span><select class="settings-select" data-field="provider">' + providerOptions(providerCatalog, account.provider, esc, [account.provider]) + '</select></label>' +
          '<label class="cloud-billing-field"><span>Label</span><input class="settings-input" data-field="label" type="text" placeholder="Label" value="' + esc(account.label || '') + '"></label>' +
          '<label class="cloud-billing-field cloud-billing-token-field"><span>Token</span><input class="settings-input" data-field="api_token" type="password" placeholder="' + esc(tokenPlaceholder) + '"></label>' +
        '</div>' +
      '</div>';
    }).join('');
    syncBillingAvailability(statusData);
  }

  function readAccountsFromDom() {
    if (!accountsEl) return accounts.slice();
    var rows = accountsEl.querySelectorAll('.cloud-billing-account');
    accounts = Array.from(rows).map(function(row) {
      var provider = row.querySelector('[data-field="provider"]');
      var label = row.querySelector('[data-field="label"]');
      var token = row.querySelector('[data-field="api_token"]');
      var enabled = row.querySelector('[data-field="enabled"]');
      var prev = accounts.find(function(account) { return account.id === row.dataset.accountId; }) || {};
      var providerValue = provider ? provider.value : (prev.provider || 'digitalocean');
      var next = {
        id: row.dataset.accountId,
        provider: providerValue,
        label: label ? label.value.trim() : (prev.label || ''),
        enabled: enabled ? !!enabled.checked : prev.enabled !== false,
        api_token_set: !!prev.api_token_set,
      };
      if (token && token.value.trim()) next.api_token = token.value.trim();
      else if (prev.api_token && !prev.api_token_set) next.api_token = prev.api_token;
      else if (prev.provider && providerValue !== prev.provider) {
        next.api_token_clear = true;
        next.api_token_set = false;
      }
      return next;
    });
    return accounts.slice();
  }

  function hasPendingTokenInput() {
    if (!accountsEl) return false;
    return Array.from(accountsEl.querySelectorAll('[data-field="api_token"]')).some(function(input) {
      return !!(input && input.value && input.value.trim());
    });
  }

  function applySettings(settings) {
    currentSettings = settings || {};
    enabledToggle.checked = !!currentSettings.cloud_billing_enabled;
    if (refreshSelect) refreshSelect.value = String(currentSettings.cloud_billing_refresh_seconds || 900);
    applyThreshold(dailyWarningInput, dailyWarningToggle, currentSettings.cloud_billing_daily_warning_usd || '');
    applyThreshold(dailyLimitInput, dailyLimitToggle, currentSettings.cloud_billing_daily_limit_usd || '');
    applyThreshold(warningInput, warningToggle, currentSettings.cloud_billing_monthly_warning_usd || '');
    applyThreshold(limitInput, limitToggle, currentSettings.cloud_billing_monthly_limit_usd || '');
    if (usageLedgerToggle) usageLedgerToggle.checked = currentSettings.cloud_billing_usage_ledger_enabled !== false;
    if (budgetEnforcedToggle) budgetEnforcedToggle.checked = currentSettings.cloud_billing_budget_enforcement_enabled !== false;
    accounts = normalizeAccounts(currentSettings.cloud_billing_accounts);
    renderAccounts();
    syncBillingAvailability();
  }

  async function loadSettings() {
    try {
      applySettings(await fetchAuthSettings());
    } catch (e) {
      setMsg('Failed to load', true);
    }
  }

  async function refreshStatus(force) {
    if (!hasConfiguredAccount()) {
      setStatus('Add a provider billing token to enable spend tracking.', false);
      syncBillingAvailability({ enabled: false, configured: false });
      return null;
    }
    try {
      var res = await fetchMonthlySpend(force);
      if (res.status === 403) {
        setStatus('Admin only', true);
        return null;
      }
      var data = await res.json();
      if (!data.enabled) {
        setStatus('Disabled', false);
      } else if (!data.configured) {
        setStatus('Add a provider billing token and save.', true);
      } else if (data.ok) {
        var basis = data.spend_scope === 'model_usage' ? 'Model usage' : 'Account spend';
        var parts = [basis + ': ' + (data.display || '--') + ' this month'];
        if (data.provider_label) parts.unshift(data.provider_label);
        if (data.budget_state && data.budget_state.block_remote_models) parts.push('remote models blocked');
        if (data.provider_display && data.spend_scope === 'model_usage') {
          parts.push('provider account total ' + data.provider_display + ' all services, not AI-only');
        }
        if (data.warning_usd) parts.push('monthly warning $' + data.warning_usd);
        if (data.limit_usd) parts.push('monthly max $' + data.limit_usd);
        if (data.cached) parts.push('cached');
        setStatus(parts.join(' · '), !!(data.over_warning || data.over_limit));
      } else if (data.over_limit) {
        setStatus(data.error || 'Cloud spend limit reached.', true);
      } else {
        setStatus(data.error || 'Model spend status unavailable', true);
      }
      renderAccounts(data);
      syncBillingAvailability(data);
      return data;
    } catch (e) {
      setStatus('Model spend status unavailable', true);
      syncBillingAvailability({ enabled: true, configured: hasConfiguredAccount(), error: 'Model spend status unavailable' });
      return null;
    }
  }

  function notifyBillingChanged() {
    try {
      window.dispatchEvent(new CustomEvent('odysseus-billing-settings-changed'));
    } catch (_) {}
  }

  function billingTestResult(data) {
    var health = data && Array.isArray(data.provider_health) ? data.provider_health : [];
    if (!health.length) {
      return {
        ok: !!(data && data.ok),
        message: data && data.ok ? 'Billing connected' : 'Billing check failed',
      };
    }
    var enabled = health.filter(function(row) { return row && row.enabled !== false && row.configured; });
    var failed = enabled.filter(function(row) { return !row.ok; });
    if (failed.length) {
      var first = failed[0];
      return {
        ok: false,
        message: 'Token saved; ' + (first.provider_label || first.account_label || 'provider') + ' check failed: ' + (first.last_error || first.status_label || first.status || 'error'),
      };
    }
    var model = enabled.filter(function(row) { return row.can_read_model_usage; });
    var account = enabled.filter(function(row) { return row.can_read_account_total; });
    if (model.length && account.length) return { ok: true, message: 'Token saved; model billing and account total connected' };
    if (model.length) return { ok: true, message: 'Token saved; model billing connected' };
    if (account.length) return { ok: true, message: 'Token saved; account total connected; model billing unavailable' };
    return { ok: false, message: 'Token saved; no billing data returned' };
  }

  async function saveBilling(options) {
    options = options || {};
    var testing = !!options.testing;
    var payloadAccounts = readAccountsFromDom();
    var configured = payloadAccounts.some(function(account) {
      return !!(account && (account.api_token_set || (account.api_token || '').trim()));
    }) || !!(usageLedgerToggle && usageLedgerToggle.checked);
    var payload = {
      cloud_billing_enabled: configured && !!enabledToggle.checked,
      cloud_billing_accounts: payloadAccounts,
      cloud_billing_refresh_seconds: parseInt(refreshSelect && refreshSelect.value, 10) || 900,
      cloud_billing_daily_warning_usd: thresholdValue(dailyWarningInput, dailyWarningToggle),
      cloud_billing_daily_limit_usd: thresholdValue(dailyLimitInput, dailyLimitToggle),
      cloud_billing_monthly_warning_usd: thresholdValue(warningInput, warningToggle),
      cloud_billing_monthly_limit_usd: thresholdValue(limitInput, limitToggle),
      cloud_billing_budget_enforcement_enabled: budgetEnforcedToggle ? !!budgetEnforcedToggle.checked : true,
      cloud_billing_usage_ledger_enabled: usageLedgerToggle ? !!usageLedgerToggle.checked : true,
    };

    try {
      setMsg(testing ? 'Saving and testing...' : 'Saving...', false);
      applySettings(await saveAuthSettings(payload));
      notifyBillingChanged();
      var data = await refreshStatus(true);
      if (testing) {
        var testResult = billingTestResult(data);
        setMsg(testResult.message, !testResult.ok);
      } else {
        setMsg('Saved', false);
        setTimeout(function() { setMsg('', false); }, 1800);
      }
    } catch (e) {
      setMsg('Failed to save', true);
    }
  }

  if (saveBtn) saveBtn.addEventListener('click', function() { saveBilling(); });
  if (refreshBtn) refreshBtn.addEventListener('click', async function() {
    if (!hasConfiguredAccount()) return;
    if (hasPendingTokenInput()) {
      await saveBilling({ testing: true });
      return;
    }
    setMsg('Refreshing...', false);
    await refreshStatus(true);
    notifyBillingChanged();
    setMsg('', false);
  });
  if (addBtn) addBtn.addEventListener('click', function() {
    accounts = readAccountsFromDom();
    var provider = (addProvider && addProvider.value) || '';
    if (!provider) {
      setMsg('Billing providers are unavailable.', true);
      return;
    }
    var tokenValue = (addToken && addToken.value.trim()) || '';
    if (!tokenValue) {
      setMsg('Enter a provider billing token before adding.', true);
      if (addToken) addToken.focus();
      return;
    }
    accounts.push({
      id: 'acct-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 7),
      provider: provider,
      label: (addLabel && addLabel.value.trim()) || providerLabel(providerCatalog, provider),
      enabled: true,
      api_token: tokenValue,
      api_token_set: false,
    });
    if (addLabel) addLabel.value = '';
    if (addToken) addToken.value = '';
    renderAccounts();
    saveBilling();
  });
  if (accountsEl) accountsEl.addEventListener('click', async function(e) {
    var testBtn = e.target.closest('[data-action="test"]');
    if (testBtn) {
      await saveBilling({ testing: true });
      return;
    }
    var removeBtn = e.target.closest('[data-action="remove"]');
    if (!removeBtn) return;
    var row = removeBtn.closest('.cloud-billing-account');
    if (!row) return;
    accounts = readAccountsFromDom().filter(function(account) { return account.id !== row.dataset.accountId; });
    renderAccounts();
    saveBilling();
  });
  enabledToggle.addEventListener('change', function() { saveBilling(); });
  if (usageLedgerToggle) usageLedgerToggle.addEventListener('change', function() { saveBilling(); });
  if (budgetEnforcedToggle) budgetEnforcedToggle.addEventListener('change', function() { saveBilling(); });
  if (refreshSelect) refreshSelect.addEventListener('change', function() { saveBilling(); });
  thresholdControls.forEach(function(control) {
    var toggle = control.toggle;
    var input = control.input;
    if (!toggle) return;
    toggle.addEventListener('change', function() {
      var disabled = !hasConfiguredAccount();
      syncThresholdControls(disabled);
      if (disabled) return;
      if (toggle.checked && !thresholdInputHasValue(input)) {
        focusThresholdInput(input);
        setMsg('Enter an amount to enable', false);
        return;
      }
      saveBilling();
    });
  });
  thresholdControls.forEach(function(control) {
    var input = control.input;
    var toggle = control.toggle;
    if (!input) return;
    input.addEventListener('focus', function() {
      if (toggle && !toggle.checked) {
        toggle.checked = true;
        syncThresholdControls(!hasConfiguredAccount());
      }
    });
    input.addEventListener('change', function() {
      if (toggle) toggle.checked = thresholdInputHasValue(input);
      syncThresholdControls(!hasConfiguredAccount());
      saveBilling();
    });
  });
  if (accountsEl) accountsEl.addEventListener('change', function(e) {
    readAccountsFromDom();
    syncBillingAvailability();
    var tokenField = e.target && e.target.closest ? e.target.closest('[data-field="api_token"]') : null;
    setMsg(tokenField ? 'Unsaved token; click Save or Test' : 'Unsaved changes', false);
  });
  if (toggleBtn) {
    toggleBtn.addEventListener('click', function() {
      setCollapsed(!(card && card.classList.contains('collapsed')));
    });
  }

  await loadProviderCatalog();
  await loadSettings();
  await refreshStatus(false);
}
