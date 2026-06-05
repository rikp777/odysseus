// Custom branch index UI. Keep custom Logbook/Billing markup out of upstream HTML.

function byId(root, id) {
  return root.getElementById ? root.getElementById(id) : root.querySelector(`#${id}`);
}

function rowForUiKey(root, key) {
  return root.querySelector(`input[data-ui-key="${key}"]`)?.closest('.vis-row');
}

function addRailLogbookButtons(root) {
  const calendar = byId(root, 'rail-calendar');
  if (!calendar) return;

  if (!byId(root, 'rail-logbook')) {
    calendar.insertAdjacentHTML('afterend', `
      <button class="icon-rail-btn" id="rail-logbook" title="Logbook"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h6M9 11h6M9 15h4"/></svg></button>
    `.trim());
  }

  const logbook = byId(root, 'rail-logbook') || calendar;
  if (!byId(root, 'rail-logbook-atlas')) {
    logbook.insertAdjacentHTML('afterend', `
      <button class="icon-rail-btn" id="rail-logbook-atlas" title="People & Places"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="3"/><path d="M2 21v-2a4 4 0 0 1 4-4h4"/><path d="M15 5l6 3-6 3-6-3 6-3z"/><path d="M9 8v8l6 3 6-3V8"/></svg></button>
    `.trim());
  }
}

function addBillingSpendPill(root) {
  if (byId(root, 'billing-spend-pill')) return;
  const sidebarInner = root.querySelector('#sidebar .sidebar-inner');
  if (!sidebarInner) return;

  sidebarInner.insertAdjacentHTML('beforebegin', `
    <button type="button" class="billing-spend-pill admin-only hidden" id="billing-spend-pill" title="Cloud month-to-date spend">
      <span class="billing-spend-provider" id="billing-spend-provider">--</span>
      <span class="billing-spend-value" id="billing-spend-value">--</span>
    </button>
  `.trim());
}

function addSidebarLogbookButtons(root) {
  const calendar = byId(root, 'tool-calendar-btn');
  if (!calendar) return;

  if (!byId(root, 'tool-logbook-btn')) {
    calendar.insertAdjacentHTML('afterend', `
      <div class="list-item" id="tool-logbook-btn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          style="flex-shrink:0;opacity:0.5;">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
          <path d="M9 7h6M9 11h6M9 15h4"/>
        </svg>
        <span class="grow">Logbook</span>
      </div>
    `.trim());
  }

  const logbook = byId(root, 'tool-logbook-btn') || calendar;
  if (!byId(root, 'tool-logbook-atlas-btn')) {
    logbook.insertAdjacentHTML('afterend', `
      <div class="list-item" id="tool-logbook-atlas-btn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          style="flex-shrink:0;opacity:0.5;">
          <circle cx="8" cy="8" r="3"/>
          <path d="M2 21v-2a4 4 0 0 1 4-4h4"/>
          <path d="M15 5l6 3-6 3-6-3 6-3z"/>
          <path d="M9 8v8l6 3 6-3V8"/>
        </svg>
        <span class="grow">People & Places</span>
      </div>
    `.trim());
  }
}

function addVisibilityRows(root) {
  const calendar = rowForUiKey(root, 'tool-calendar');
  if (!calendar) return;

  if (!rowForUiKey(root, 'tool-logbook')) {
    calendar.insertAdjacentHTML('afterend', `
      <label class="vis-row">
        <span class="vis-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h6M9 11h6M9 15h4"/></svg></span>
        <span class="vis-label">Logbook</span>
        <input type="checkbox" checked data-ui-key="tool-logbook"><span class="vis-switch"></span>
      </label>
    `.trim());
  }

  const logbook = rowForUiKey(root, 'tool-logbook') || calendar;
  if (!rowForUiKey(root, 'tool-logbook-atlas')) {
    logbook.insertAdjacentHTML('afterend', `
      <label class="vis-row">
        <span class="vis-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="3"/><path d="M2 21v-2a4 4 0 0 1 4-4h4"/><path d="M15 5l6 3-6 3-6-3 6-3z"/><path d="M9 8v8l6 3 6-3V8"/></svg></span>
        <span class="vis-label">People & Places</span>
        <input type="checkbox" checked data-ui-key="tool-logbook-atlas"><span class="vis-switch"></span>
      </label>
    `.trim());
  }
}

function addDigitalOceanProvider(root) {
  const select = byId(root, 'adm-epProvider');
  if (!select || select.querySelector('option[data-logo="digitalocean"]')) return;

  const option = document.createElement('option');
  option.value = 'https://inference.do-ai.run/v1';
  option.dataset.logo = 'digitalocean';
  option.textContent = 'DigitalOcean Inference';

  const deepseek = select.querySelector('option[data-logo="deepseek"]');
  if (deepseek) {
    deepseek.insertAdjacentElement('afterend', option);
  } else {
    select.append(option);
  }
}

function addCloudBillingSettingsCard(root) {
  if (byId(root, 'cloud-billing-card')) return;
  const addedModelsCard = byId(root, 'adm-epList-api')?.closest('.admin-card');
  if (!addedModelsCard) return;

  addedModelsCard.insertAdjacentHTML('afterend', `
    <div class="admin-card admin-only cloud-billing-card collapsed" id="cloud-billing-card">
      <button type="button" class="cloud-billing-toggle" id="set-cloudBillingToggle" aria-expanded="false">
        <span class="cloud-billing-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7H14.5a3.5 3.5 0 0 1 0 7H6"/></svg>Model Spend</span>
        <span class="cloud-billing-summary" id="set-cloudBillingSummary">Optional</span>
        <svg class="cloud-billing-caret" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="cloud-billing-body" id="set-cloudBillingBody">
        <div class="admin-toggle-sub" style="margin-bottom:10px">Enable model spend tracking, chat cost labels, and model price badges.</div>
        <div class="settings-col">
        <details class="cloud-billing-info">
          <summary>How Spend Is Calculated</summary>
          <div class="cloud-billing-info-body">
            <p><strong>Model spend</strong> is the AI/model usage total used for the sidebar, chat cost labels, spending graphs, warnings, and max usage limits.</p>
            <p><strong>Provider account total</strong> is the provider's full account bill. For DigitalOcean this can include droplets, storage, networking, and AI services. It is shown for context in settings only and is not added to model spend.</p>
          </div>
        </details>
        <div class="cloud-billing-current is-loading" id="set-cloudBillingCurrentSpend" aria-live="polite">
          <div class="cloud-billing-current-main">
            <div>
              <span>Current AI Spend</span>
              <strong>--</strong>
            </div>
            <span class="cloud-billing-current-period">Month to date</span>
          </div>
          <div class="cloud-billing-current-meta">Refresh billing to show model usage.</div>
        </div>
        <details class="cloud-billing-diagnostics" id="set-cloudBillingDiagnostics">
          <summary>
            <span>Spend Audit</span>
            <span id="set-cloudBillingAuditSummary">No data</span>
          </summary>
          <div class="cloud-billing-diagnostics-body" id="set-cloudBillingAudit"></div>
        </details>
        <details class="cloud-billing-diagnostics cloud-billing-events" id="set-cloudBillingEventsPanel">
          <summary>
            <span>Budget Activity</span>
            <span id="set-cloudBillingEventsSummary">No events</span>
          </summary>
          <div class="cloud-billing-diagnostics-body" id="set-cloudBillingEvents"></div>
        </details>
        <div class="cloud-billing-control-grid" aria-label="Model spend controls">
          <div class="cloud-billing-control cloud-billing-control-primary">
            <label class="cloud-billing-control-copy" for="set-cloudBillingEnabled">
              <strong>Enabled</strong>
              <span>Show model spend in the sidebar, chat, and model picker.</span>
            </label>
            <label class="admin-switch cloud-billing-control-switch" title="Show model spend in the sidebar and cost labels in chat"><input type="checkbox" id="set-cloudBillingEnabled"><span class="admin-slider"></span></label>
          </div>
          <div class="cloud-billing-control">
            <label class="cloud-billing-control-copy" for="set-cloudBillingUsageLedger">
              <strong>Usage Ledger</strong>
              <span>Track token usage for provider-generic spend graphs.</span>
            </label>
            <label class="admin-switch cloud-billing-control-switch" title="Track local model token usage for provider-generic spend graphs and budgets"><input type="checkbox" id="set-cloudBillingUsageLedger"><span class="admin-slider"></span></label>
          </div>
          <div class="cloud-billing-control">
            <label class="cloud-billing-control-copy" for="set-cloudBillingBudgetEnforced">
              <strong>Enforce Budgets</strong>
              <span>Block remote model calls after max usage is reached.</span>
            </label>
            <label class="admin-switch cloud-billing-control-switch" title="Block remote model calls when local spend budgets are reached"><input type="checkbox" id="set-cloudBillingBudgetEnforced"><span class="admin-slider"></span></label>
          </div>
          <div class="cloud-billing-control cloud-billing-refresh-control">
            <label class="cloud-billing-control-copy" for="set-cloudBillingRefresh">
              <strong>Refresh</strong>
              <span>Provider billing cache interval.</span>
            </label>
            <select id="set-cloudBillingRefresh" class="settings-select">
              <option value="300">5 min</option>
              <option value="900">15 min</option>
              <option value="1800">30 min</option>
              <option value="3600">1 hour</option>
            </select>
          </div>
        </div>
        <div class="cloud-billing-budget-table" aria-label="Model spend thresholds">
          <div class="cloud-billing-budget-head">Period</div>
          <div class="cloud-billing-budget-head">Warning</div>
          <div class="cloud-billing-budget-head">Max usage</div>
          <div class="cloud-billing-budget-period">
            <strong>Daily</strong>
            <span>Usage ledger</span>
          </div>
          <div class="cloud-billing-budget-cell">
            <label class="admin-switch cloud-billing-budget-switch" title="Warn when today's model spend reaches this amount"><input type="checkbox" id="set-cloudBillingDailyWarningToggle"><span class="admin-slider"></span></label>
            <input id="set-cloudBillingDailyWarning" type="text" inputmode="decimal" class="settings-input" placeholder="USD" aria-label="Daily warning USD">
          </div>
          <div class="cloud-billing-budget-cell">
            <label class="admin-switch cloud-billing-budget-switch" title="Block remote models when today's spend reaches this amount"><input type="checkbox" id="set-cloudBillingDailyLimitToggle"><span class="admin-slider"></span></label>
            <input id="set-cloudBillingDailyLimit" type="text" inputmode="decimal" class="settings-input" placeholder="USD" aria-label="Daily max usage USD">
          </div>
          <div class="cloud-billing-budget-period">
            <strong>Monthly</strong>
            <span>Month to date</span>
          </div>
          <div class="cloud-billing-budget-cell">
            <label class="admin-switch cloud-billing-budget-switch" title="Warn when monthly model spend reaches this amount"><input type="checkbox" id="set-cloudBillingWarningToggle"><span class="admin-slider"></span></label>
            <input id="set-cloudBillingWarning" type="text" inputmode="decimal" class="settings-input" placeholder="USD" aria-label="Monthly warning USD">
          </div>
          <div class="cloud-billing-budget-cell">
            <label class="admin-switch cloud-billing-budget-switch" title="Block remote models when monthly spend reaches this amount"><input type="checkbox" id="set-cloudBillingLimitToggle"><span class="admin-slider"></span></label>
            <input id="set-cloudBillingLimit" type="text" inputmode="decimal" class="settings-input" placeholder="USD" aria-label="Monthly max usage USD">
          </div>
        </div>
        <div class="cloud-billing-provider-section">
          <div class="cloud-billing-section-head">
            <strong>Provider Accounts</strong>
            <span>Optional billing API connections. Account totals are full provider spend across all services, not AI-only.</span>
          </div>
          <div id="set-cloudBillingAccounts" class="cloud-billing-accounts"></div>
          <div class="cloud-billing-add-card">
            <div class="cloud-billing-add-copy">
              <strong>Add Provider Account</strong>
              <span>Saved tokens are hidden after save.</span>
            </div>
            <div class="cloud-billing-add-row">
              <select id="set-cloudBillingAddProvider" class="settings-select" title="Provider">
                <option value="">Loading providers...</option>
              </select>
              <input id="set-cloudBillingAddLabel" type="text" class="settings-input" placeholder="Label">
              <input id="set-cloudBillingAddToken" type="password" class="settings-input" placeholder="Provider billing API token">
              <button type="button" class="admin-btn-sm" id="set-cloudBillingAdd">Add</button>
            </div>
          </div>
        </div>
        <div class="settings-row" style="margin-top:4px">
          <button type="button" class="admin-btn-sm" id="set-cloudBillingSave">Save</button>
          <button type="button" class="admin-btn-sm" id="set-cloudBillingRefreshNow">Refresh</button>
          <span id="set-cloudBillingMsg" style="font-size:11px"></span>
        </div>
        <div id="set-cloudBillingStatus" class="billing-settings-status"></div>
      </div>
      </div>
    </div>
  `.trim());
}

export function installCustomIndexUi(root = document) {
  if (!root?.querySelector) return;
  addRailLogbookButtons(root);
  addBillingSpendPill(root);
  addSidebarLogbookButtons(root);
  addVisibilityRows(root);
  addDigitalOceanProvider(root);
  addCloudBillingSettingsCard(root);
}

function bootCustomIndexUi() {
  installCustomIndexUi(document);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootCustomIndexUi, { once: true });
} else {
  bootCustomIndexUi();
}
