// static/js/markdown.js

/**
 * Markdown rendering and content processing utilities
 */

import uiModule from './ui.js';
import { splitTableRow } from './markdown/tableRow.js';
import { replaceEmojiShortcodes, hasEmojiShortcode } from './emojiShortcodes.js';

var escapeHtml = uiModule.esc;

function safeLinkUrl(rawUrl) {
  const url = String(rawUrl || '').trim();
  if (url.startsWith('#')) {
    return /^#[A-Za-z0-9_-]*$/.test(url) ? url : '';
  }
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href;
    }
  } catch (_) {
    return '';
  }
  return '';
}

function linkHtml(text, url) {
  const safeUrl = safeLinkUrl(url);
  const safeText = escapeHtml(text);
  if (!safeUrl) return safeText;
  if (safeUrl.startsWith('#')) {
    return `<a href="${safeUrl}" class="chat-link">${safeText}</a>`;
  }
  return `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${safeText}</a>`;
}

function _billingChartNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(0, n) : 0;
}

function _billingChartMoney(value, fallback) {
  if (fallback) return escapeHtml(String(fallback));
  const n = _billingChartNumber(value);
  return '$' + (n < 1 ? n.toFixed(2) : n.toFixed(2).replace(/\.00$/, ''));
}

function _billingChartWhole(value) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(0, Math.round(n)) : 0;
}

function _billingChartCompact(value) {
  const n = _billingChartWhole(value);
  if (n >= 1000000) return (n / 1000000).toFixed(n >= 10000000 ? 0 : 1).replace(/\.0$/, '') + 'M';
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '') + 'K';
  return String(n);
}

function _billingChartUsageMeta(usage) {
  if (!usage || typeof usage !== 'object') return '';
  const totalTokens = _billingChartWhole(usage.total_tokens);
  const events = _billingChartWhole(usage.events);
  const unknownCostEvents = _billingChartWhole(usage.unknown_cost_events);
  const parts = [];
  if (totalTokens) parts.push(`${_billingChartCompact(totalTokens)} tokens`);
  if (events) parts.push(`${events} ${events === 1 ? 'call' : 'calls'}`);
  if (unknownCostEvents) parts.push(`${unknownCostEvents} unpriced`);
  return parts.join(' | ');
}

function _billingChartSourceKind(item) {
  if (!item || typeof item !== 'object') return '';
  const explicit = String(item.source_kind || '').toLowerCase();
  if (explicit) return explicit;
  const provider = String(item.provider || '').toLowerCase();
  const providerLabel = String(item.provider_label || '').toLowerCase();
  if (provider === 'local_usage' || providerLabel === 'local usage') return 'usage_ledger';
  return provider ? 'provider_billing' : '';
}

function _billingChartSourceNote(chart, accounts, usage) {
  const explicit = String(chart?.source_note || '').trim();
  if (
    explicit
    && chart?.spend_scope === 'model_usage'
    && explicit.includes('provider billing is account-level')
  ) {
    if (chart?.spend_source === 'provider_model_billing') return 'Model spend from provider billing insights';
    if (chart?.spend_source === 'usage_ledger') return 'Model spend from usage ledger estimates';
  }
  if (explicit) return explicit;
  if (chart?.spend_source === 'usage_ledger') {
    return 'Model spend from usage ledger estimates';
  }
  const hasUsage = !!(
    _billingChartWhole(usage?.events) ||
    _billingChartWhole(usage?.total_tokens) ||
    accounts.some(item => _billingChartSourceKind(item) === 'usage_ledger')
  );
  const hasProvider = accounts.some(item => _billingChartSourceKind(item) === 'provider_billing');
  if (hasProvider && hasUsage) return 'Account total from provider billing; usage rows are estimates';
  if (hasUsage) return 'Model spend from usage ledger estimates';
  if (hasProvider) return 'Account total from provider billing';
  return '';
}

function _billingChartNotice(chart) {
  const notice = String(chart?.notice || '').trim();
  if (!notice) return '';
  if (
    chart?.spend_scope === 'model_usage'
    && /^Provider account billing reports\b/.test(notice)
  ) {
    return '';
  }
  return notice;
}

function _billingChartDateLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function _billingChartMonthLabel(chart) {
  const explicit = String(chart?.month_label || '').trim();
  if (explicit) return explicit;
  const month = String(chart?.month || '').trim();
  if (/^\d{4}-\d{2}$/.test(month)) {
    const date = new Date(`${month}-01T12:00:00Z`);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    }
  }
  return '';
}

function _billingChartMonthNav(chart) {
  const period = String(chart?.period || 'month').toLowerCase();
  const month = String(chart?.month || '').trim();
  if (period !== 'month' || !/^\d{4}-\d{2}$/.test(month)) return '';

  const label = _billingChartMonthLabel(chart) || month;
  const previousMonth = String(chart?.previous_month || '').trim();
  const nextMonth = String(chart?.next_month || '').trim();
  const previousDisabled = /^\d{4}-\d{2}$/.test(previousMonth) ? '' : ' disabled';
  const nextDisabled = /^\d{4}-\d{2}$/.test(nextMonth) ? '' : ' disabled';
  const previousTarget = previousDisabled ? '' : previousMonth;
  const nextTarget = nextDisabled ? '' : nextMonth;

  return `
        <div class="billing-chart-month-nav" aria-label="Billing month">
          <button
            type="button"
            class="billing-chart-month-button"
            data-billing-chart-month="${escapeHtml(previousTarget)}"
            aria-label="Previous billing month"${previousDisabled}
          ><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 18l-6-6 6-6"></path></svg></button>
          <span class="billing-chart-month-label">${escapeHtml(label)}</span>
          <button
            type="button"
            class="billing-chart-month-button"
            data-billing-chart-month="${escapeHtml(nextTarget)}"
            aria-label="Next billing month"${nextDisabled}
          ><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg></button>
        </div>
      `;
}

function _billingChartPointLabel(item) {
  const date = _billingChartDateLabel(item?.timestamp) || item?.timestamp || 'Point';
  const amount = _billingChartMoney(_billingChartNumber(item?.amount), item?.display);
  return `${date}: ${amount}`;
}

function _billingChartDayOfMonth(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.getUTCDate();
}

function _billingChartMonthEndLabel(chart, points) {
  const daysInMonth = _billingChartWhole(chart?.days_in_month);
  if (!daysInMonth) return 'Month end';
  const source = chart?.updated_at || points[points.length - 1]?.timestamp;
  const date = new Date(source);
  if (Number.isNaN(date.getTime())) return 'Month end';
  const monthEnd = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), daysInMonth, 12));
  return _billingChartDateLabel(monthEnd.toISOString()) || 'Month end';
}

function _billingChartProjectionAvailable(chart, points) {
  const period = String(chart?.period || 'month').toLowerCase();
  const projected = _billingChartNumber(chart?.projected);
  const total = _billingChartNumber(chart?.total);
  const daysInMonth = _billingChartWhole(chart?.days_in_month);
  const daysElapsed = _billingChartWhole(chart?.days_elapsed);
  return (
    period === 'month'
    && points.length >= 2
    && projected > 0
    && projected > total
    && daysInMonth > 1
    && daysElapsed > 0
    && daysElapsed < daysInMonth
  );
}

function _billingChartThresholds(chart) {
  const period = String(chart?.period || 'month').toLowerCase();
  const config = period === 'day'
    ? {
      warning: chart?.daily_warning,
      warningDisplay: chart?.daily_warning_display,
      warningLabel: 'Day warn',
      limit: chart?.daily_limit,
      limitDisplay: chart?.daily_limit_display,
      limitLabel: 'Day max',
      ariaLabel: 'Show daily warning and max usage lines',
    }
    : period === 'month'
      ? {
        warning: chart?.monthly_warning,
        warningDisplay: chart?.monthly_warning_display,
        warningLabel: 'Month warn',
        limit: chart?.monthly_limit,
        limitDisplay: chart?.monthly_limit_display,
        limitLabel: 'Month max',
        ariaLabel: 'Show monthly warning and max usage lines',
      }
      : null;
  if (!config) return [];
  const thresholds = [];
  if (config.warning != null) {
    const amount = _billingChartNumber(config.warning);
    if (amount > 0) {
      thresholds.push({
        kind: 'warning',
        label: config.warningLabel,
        amount,
        display: config.warningDisplay,
      });
    }
  }
  if (config.limit != null) {
    const amount = _billingChartNumber(config.limit);
    if (amount > 0) {
      thresholds.push({
        kind: 'limit',
        label: config.limitLabel,
        amount,
        display: config.limitDisplay,
      });
    }
  }
  thresholds.ariaLabel = config.ariaLabel;
  return thresholds;
}

function _billingChartCoords(points, chart, dims, safeMax, mode) {
  const { h, padX, padY, usableW, usableH } = dims;
  const daysInMonth = _billingChartWhole(chart?.days_in_month);
  const daysElapsed = Math.min(daysInMonth || 1, Math.max(1, _billingChartWhole(chart?.days_elapsed)));
  return points.map((item, idx) => {
    let x;
    if (mode === 'month' && daysInMonth > 1) {
      const fallbackDay = 1 + (idx * Math.max(0, daysElapsed - 1) / Math.max(1, points.length - 1));
      const day = _billingChartDayOfMonth(item?.timestamp) || fallbackDay;
      const clampedDay = Math.max(1, Math.min(daysInMonth, day));
      x = padX + ((clampedDay - 1) * usableW / Math.max(1, daysInMonth - 1));
    } else {
      x = padX + (idx * usableW / Math.max(1, points.length - 1));
    }
    const y = h - padY - ((_billingChartNumber(item.amount) / safeMax) * usableH);
    return [Number(x.toFixed(2)), Number(y.toFixed(2))];
  });
}

function _billingChartPointControl(pair, label, dims, classNames) {
  const left = (pair[0] / dims.w) * 100;
  const top = (pair[1] / dims.h) * 100;
  const classes = ['billing-chart-point', ...classNames].filter(Boolean).join(' ');
  return `
      <button
        type="button"
        class="${classes}"
        style="left:${left.toFixed(4)}%;top:${top.toFixed(4)}%;"
        data-chart-x="${left.toFixed(4)}"
        data-chart-y="${top.toFixed(4)}"
        aria-label="${escapeHtml(label)}"
        title="${escapeHtml(label)}"
      ><span>${escapeHtml(label)}</span></button>
    `;
}

function _billingChartLayer(coords, dims, classes = '') {
  const line = coords.map(pair => pair.join(',')).join(' ');
  const baseline = dims.h - dims.padY;
  const area = `${coords[0][0]},${baseline} ${line} ${coords[coords.length - 1][0]},${baseline}`;
  const classAttr = classes ? ` class="${classes}"` : '';
  return `
        <g${classAttr}>
          <polygon class="billing-chart-area" points="${area}"></polygon>
          <polyline class="billing-chart-line" points="${line}"></polyline>
          ${coords.map(pair => `<circle class="billing-chart-dot" cx="${pair[0]}" cy="${pair[1]}" r="3"></circle>`).join('')}
        </g>
  `;
}

function _billingChartThresholdLayer(thresholds, dims, safeMax) {
  if (!thresholds.length) return '';
  const { w, padX, padY, usableH } = dims;
  const baseline = dims.h - padY;
  const rows = thresholds.map(item => {
    const y = Math.max(padY + 4, Math.min(baseline - 4, baseline - ((item.amount / safeMax) * usableH)));
    const display = _billingChartMoney(item.amount, item.display);
    const title = `${item.label}: ${display}`;
    return `
        <g class="billing-chart-threshold billing-chart-threshold-${escapeHtml(item.kind)}">
          <title>${escapeHtml(title)}</title>
          <line x1="${padX}" y1="${y.toFixed(2)}" x2="${w - padX}" y2="${y.toFixed(2)}"></line>
          <text x="${w - padX - 4}" y="${Math.max(padY + 9, y - 5).toFixed(2)}">${escapeHtml(title)}</text>
        </g>
      `;
  }).join('');
  return `<g class="billing-chart-threshold-layer">${rows}</g>`;
}

function _billingChartSvg(history, maxY, chart = {}) {
  if (!Array.isArray(history) || history.length < 2) return '';
  const points = history
    .filter(item => item && Number.isFinite(Number(item.amount)))
    .slice(-30);
  if (points.length < 2) return '';

  const w = 520;
  const h = 150;
  const padX = 22;
  const padY = 18;
  const usableW = w - (padX * 2);
  const usableH = h - (padY * 2);
  const dims = { w, h, padX, padY, usableW, usableH };
  const safeMax = Math.max(0.01, maxY);
  const coords = _billingChartCoords(points, chart, dims, safeMax, 'spread');
  const hasProjection = _billingChartProjectionAvailable(chart, points);
  const thresholds = _billingChartThresholds(chart);
  const hasThresholds = thresholds.length > 0;
  const monthCoords = hasProjection ? _billingChartCoords(points, chart, dims, safeMax, 'month') : [];
  const projectedAmount = _billingChartNumber(chart?.projected);
  const projectedY = h - padY - ((projectedAmount / safeMax) * usableH);
  const projectedCoord = [w - padX, Number(projectedY.toFixed(2))];
  const firstLabel = _billingChartDateLabel(points[0]?.timestamp);
  const lastLabel = _billingChartDateLabel(points[points.length - 1]?.timestamp);
  const monthEndLabel = hasProjection ? _billingChartMonthEndLabel(chart, points) : '';
  const actualPointControls = coords.map((pair, idx) => {
    const label = _billingChartPointLabel(points[idx]);
    const edge = idx === 0 ? 'edge-start' : idx === coords.length - 1 ? 'edge-end' : '';
    return _billingChartPointControl(pair, label, dims, ['billing-chart-actual-point', edge]);
  }).join('');
  const projectionPointControls = hasProjection
    ? monthCoords.map((pair, idx) => {
      const label = _billingChartPointLabel(points[idx]);
      const edge = idx === 0 ? 'edge-start' : '';
      return _billingChartPointControl(pair, label, dims, ['billing-chart-projection-mode-point', edge]);
    }).join('')
    : '';
  const projectedLabel = `Projected month-end: ${_billingChartMoney(projectedAmount, chart?.projected_display)}`;
  const projectedControl = hasProjection
    ? _billingChartPointControl(projectedCoord, projectedLabel, dims, ['billing-chart-projected-point', 'edge-end'])
    : '';
  const projectionLayer = hasProjection
    ? `
        <g class="billing-chart-projection-mode-layer">
          ${_billingChartLayer(monthCoords, dims)}
          <polyline class="billing-chart-projection-line" points="${monthCoords[monthCoords.length - 1].join(',')} ${projectedCoord.join(',')}"></polyline>
          <circle class="billing-chart-projected-dot" cx="${projectedCoord[0]}" cy="${projectedCoord[1]}" r="3.5"></circle>
        </g>
      `
    : '';
  const thresholdLayer = hasThresholds ? _billingChartThresholdLayer(thresholds, dims, safeMax) : '';
  const actionItems = [];
  if (hasThresholds) {
    actionItems.push(`
        <label class="billing-chart-graph-toggle billing-chart-threshold-toggle">
          <input type="checkbox" class="billing-chart-toggle-input billing-chart-threshold-input" aria-label="${escapeHtml(thresholds.ariaLabel || 'Show warning and max usage lines')}" checked>
          <span class="billing-chart-toggle-switch billing-chart-threshold-switch" aria-hidden="true"></span>
          <span>Limits</span>
        </label>
      `);
  }
  if (hasProjection) {
    actionItems.push(`
        <label class="billing-chart-graph-toggle billing-chart-projection-toggle">
          <input type="checkbox" class="billing-chart-toggle-input billing-chart-projection-input" aria-label="Show projected spend line">
          <span class="billing-chart-toggle-switch billing-chart-projection-switch" aria-hidden="true"></span>
          <span>Projected</span>
        </label>
      `);
  }
  const plotActions = actionItems.length
    ? `
      <div class="billing-chart-plot-actions">
        ${actionItems.join('')}
      </div>
    `
    : '';
  return `
    <div class="billing-chart-plot${hasThresholds ? ' show-thresholds' : ''}">
      ${plotActions}
      <div class="billing-chart-plot-frame">
        <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Billing spend history">
          <line class="billing-chart-axis" x1="${padX}" y1="${h - padY}" x2="${w - padX}" y2="${h - padY}"></line>
          <line class="billing-chart-axis" x1="${padX}" y1="${padY}" x2="${padX}" y2="${h - padY}"></line>
          ${thresholdLayer}
          ${_billingChartLayer(coords, dims, 'billing-chart-actual-layer')}
          ${projectionLayer}
        </svg>
        ${actualPointControls}
        ${projectionPointControls}
        ${projectedControl}
      </div>
      <div class="billing-chart-axis-labels billing-chart-axis-labels-actual"><span>${escapeHtml(firstLabel)}</span><span>${escapeHtml(lastLabel)}</span></div>
      ${hasProjection ? `<div class="billing-chart-axis-labels billing-chart-axis-labels-projected"><span>${escapeHtml(firstLabel)}</span><span>${escapeHtml(monthEndLabel)}</span></div>` : ''}
    </div>
  `;
}

function _billingChartDataPoints(history, chart = {}) {
  if (!Array.isArray(history)) return '';
  const points = history
    .filter(item => item && Number.isFinite(Number(item.amount)))
    .slice(-30);
  if (!points.length) return '';

  const rows = points.map(item => {
    const date = _billingChartDateLabel(item?.timestamp) || item?.timestamp || 'Point';
    const tag = item?.synthetic ? 'Baseline' : 'Actual';
    return `
      <div class="billing-chart-data-row">
        <span>
          <strong>${escapeHtml(date)}</strong>
          <span class="billing-chart-data-tag">${tag}</span>
        </span>
        <span>${_billingChartMoney(_billingChartNumber(item.amount), item.display)}</span>
      </div>
    `;
  });

  const hasProjection = _billingChartProjectionAvailable(chart, points);
  if (hasProjection) {
    rows.push(`
      <div class="billing-chart-data-row billing-chart-data-row-projected">
        <span>
          <strong>${escapeHtml(_billingChartMonthEndLabel(chart, points))}</strong>
          <span class="billing-chart-data-tag">Projected</span>
        </span>
        <span>${_billingChartMoney(_billingChartNumber(chart.projected), chart.projected_display)}</span>
      </div>
    `);
  }

  const pointLabel = `${points.length} ${points.length === 1 ? 'point' : 'points'}`;
  const projectionLabel = hasProjection ? ' + projection' : '';
  return `
    <details class="billing-chart-data-points">
      <summary>
        <span>Data points</span>
        <span>${escapeHtml(pointLabel + projectionLabel)}</span>
      </summary>
      <div class="billing-chart-data-list">${rows.join('')}</div>
    </details>
  `;
}

function _billingChartHtml(raw) {
  let chart;
  try {
    chart = JSON.parse(raw || '{}');
  } catch (_) {
    return '<pre><code class="language-json">Invalid billing chart data</code></pre>';
  }
  if (!chart || typeof chart !== 'object' || chart.kind !== 'billing-spend') {
    return '<pre><code class="language-json">Unsupported billing chart data</code></pre>';
  }

  const accounts = Array.isArray(chart.accounts) ? chart.accounts : [];
  const history = Array.isArray(chart.history) ? chart.history : [];
  const usage = chart.usage && typeof chart.usage === 'object' ? chart.usage : {};
  const usageTokens = _billingChartWhole(usage.total_tokens);
  const usageEvents = _billingChartWhole(usage.events);
  const total = _billingChartNumber(chart.total);
  const projected = _billingChartNumber(chart.projected);
  const limit = chart.limit == null ? null : _billingChartNumber(chart.limit);
  const warning = chart.warning == null ? null : _billingChartNumber(chart.warning);
  const maxAccount = Math.max(0.01, ...accounts.map(item => _billingChartNumber(item && item.amount)));
  const maxY = Math.max(0.01, total, projected, limit || 0, warning || 0, ...history.map(item => _billingChartNumber(item && item.amount)));
  const budgetTarget = limit || warning || maxY;
  const budgetPct = Math.max(0, Math.min(100, (total / Math.max(0.01, budgetTarget)) * 100));
  const budgetClass = limit && total >= limit ? ' over-limit' : warning && total >= warning ? ' over-warning' : '';
  const title = escapeHtml(chart.title || 'Model Spend');
  const subtitle = escapeHtml(chart.subtitle || '');
  const chartPeriod = String(chart.period || 'month').toLowerCase();
  const monthNav = _billingChartMonthNav(chart);
  const sourceNote = _billingChartSourceNote(chart, accounts, usage);
  const noticeText = _billingChartNotice(chart);
  const notice = noticeText ? `<div class="billing-chart-notice">${escapeHtml(noticeText)}</div>` : '';
  const updated = chart.updated_at ? `<span>Updated ${escapeHtml(_billingChartDateLabel(chart.updated_at) || chart.updated_at)}</span>` : '';

  const statItems = [['Current', _billingChartMoney(total, chart.total_display)]];
  if (chart.is_current_month !== false) {
    statItems.push(['Projected', _billingChartMoney(projected, chart.projected_display)]);
  }
  if (limit != null) statItems.push([chartPeriod === 'day' ? 'Daily Max' : 'Monthly Max', _billingChartMoney(limit, chart.limit_display)]);
  else if (warning != null) statItems.push([chartPeriod === 'day' ? 'Daily Warning' : 'Monthly Warning', _billingChartMoney(warning, chart.warning_display)]);
  if (usageTokens) statItems.push(['Tokens', _billingChartCompact(usageTokens)]);
  if (usageEvents) statItems.push(['Calls', String(usageEvents)]);
  const budgetLabel = limit != null
    ? (chartPeriod === 'day' ? 'daily max' : 'monthly max')
    : warning != null
      ? (chartPeriod === 'day' ? 'warning' : 'monthly warning')
      : 'current scale';

  const accountRows = accounts.length
    ? accounts.map(item => {
      const amount = _billingChartNumber(item && item.amount);
      const width = Math.max(2, Math.min(100, (amount / maxAccount) * 100));
      const label = escapeHtml(item?.label || item?.provider_label || 'Cloud');
      const metaParts = [];
      if (item?.provider_label) metaParts.push(`<span>${escapeHtml(item.provider_label)}</span>`);
      if (item?.source_label && item.source_label !== item?.provider_label) {
        metaParts.push(`<span class="billing-chart-source-chip">${escapeHtml(item.source_label)}</span>`);
      }
      const usageMeta = _billingChartUsageMeta(item?.usage || item);
      if (usageMeta) metaParts.push(`<span>${escapeHtml(usageMeta)}</span>`);
      const error = item?.ok === false && item?.error ? `<span class="billing-chart-row-error">${escapeHtml(item.error)}</span>` : '';
      if (error) metaParts.push(error);
      return `
        <div class="billing-chart-row">
          <div class="billing-chart-row-top"><span>${label}</span><span>${_billingChartMoney(amount, item?.display)}</span></div>
          <div class="billing-chart-bar"><span style="width:${width.toFixed(2)}%"></span></div>
          <div class="billing-chart-row-meta">${metaParts.join('')}</div>
        </div>
      `;
    }).join('')
    : '<div class="billing-chart-empty">No provider spend or usage has been recorded yet.</div>';

  return `
    <div
      class="billing-chart-card"
      data-billing-chart-card="1"
      data-billing-month="${escapeHtml(chart.month || '')}"
      data-billing-group-by="${escapeHtml(chart.group_by || 'provider')}"
      data-billing-provider-query="${escapeHtml(chart.provider_query || '')}"
      data-billing-spend-source="${escapeHtml(chart.spend_source || '')}"
      data-billing-spend-scope="${escapeHtml(chart.spend_scope || '')}"
    >
      <div class="billing-chart-head">
        <div class="billing-chart-heading">
          <div class="billing-chart-title-row">
            <div class="billing-chart-title">${title}</div>
            ${monthNav}
          </div>
          <div class="billing-chart-subtitle">${subtitle}</div>
          ${sourceNote ? `<div class="billing-chart-source-note">${escapeHtml(sourceNote)}</div>` : ''}
        </div>
        <div class="billing-chart-total">${_billingChartMoney(total, chart.total_display)}</div>
      </div>
      <div class="billing-chart-stats">
        ${statItems.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${value}</strong></div>`).join('')}
      </div>
      <div class="billing-chart-budget${budgetClass}">
        <div class="billing-chart-budget-track"><span style="width:${budgetPct.toFixed(2)}%"></span></div>
        <div class="billing-chart-budget-labels"><span>${budgetPct.toFixed(0)}% of ${budgetLabel}</span>${updated}</div>
      </div>
      ${_billingChartSvg(history, maxY, chart)}
      ${_billingChartDataPoints(history, chart)}
      <div class="billing-chart-accounts">${accountRows}</div>
      ${notice}
    </div>
  `;
}

/**
 * Sanitize the raw-HTML fragments that mdToHtml deliberately preserves from
 * the source text — <details> blocks (collapsible agent output) and <a> tags
 * (emitted by the markdown link pass). Those fragments are later restored
 * verbatim into innerHTML, so without scrubbing them a model — or any content
 * routed through here — could smuggle in an `<img onerror=...>`, an
 * `<a href="javascript:...">`, an `onmouseover=` handler, etc. and execute
 * script in the authenticated page (DOM XSS).
 *
 * Parsing into a <template> is inert: assigning to template.innerHTML neither
 * fetches resources nor runs scripts, so we can walk the resulting tree,
 * drop script-capable elements, and strip event-handler attributes and
 * dangerous URL schemes before the (now safe) fragment is handed back.
 */
const _ALLOWED_HTML_BAD_TAGS = new Set([
  'SCRIPT', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META',
  'STYLE', 'BASE', 'FORM', 'NOSCRIPT', 'TEMPLATE',
  // Foreign-content roots. SVG/MathML have their own parser rules and are a
  // classic mutation-XSS vehicle — e.g. an SVG-namespaced <script>, whose
  // `tagName` is the lower-case 'script' and would slip a name check that
  // assumed HTML's upper-casing. They aren't needed in the <details>/<a>
  // fragments we preserve, so drop the whole subtree.
  'SVG', 'MATH',
]);
const _ALLOWED_HTML_URL_ATTRS = new Set([
  'href', 'src', 'srcset', 'xlink:href', 'action', 'formaction', 'background', 'poster',
]);

function _compactUrlSchemeValue(value) {
  return String(value || '').replace(/[\u0000-\u0020\u007f-\u009f]+/g, '').toLowerCase();
}

function _isDangerousUrl(value) {
  return /^(javascript|vbscript|data):/.test(_compactUrlSchemeValue(value));
}

function _isDangerousSrcset(value) {
  return String(value || '').split(',').some(candidate => _isDangerousUrl(candidate));
}

function _cleanAllowedHtmlOnce(htmlString) {
  const tpl = document.createElement('template');
  tpl.innerHTML = htmlString;
  for (const el of Array.from(tpl.content.querySelectorAll('*'))) {
    // Upper-case the tag for comparison: HTML tagNames are upper-case, but
    // SVG/MathML elements preserve their original (lower/camel) case, so a
    // raw `Set.has(el.tagName)` would miss e.g. a namespaced <script>.
    if (_ALLOWED_HTML_BAD_TAGS.has(el.tagName.toUpperCase())) {
      el.remove();
      continue;
    }
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      // Drop every inline event handler (onerror, onclick, onmouseover, ...)
      // and srcdoc (a frame-less script vector).
      if (name.startsWith('on') || name === 'srcdoc') {
        el.removeAttribute(attr.name);
        continue;
      }
      if (name === 'style') {
        const value = _compactUrlSchemeValue(attr.value);
        if (/javascript:|vbscript:|data:|expression\(/.test(value)) {
          el.removeAttribute(attr.name);
        }
        continue;
      }
      // Neutralize javascript:/vbscript:/data: in URL-bearing attributes.
      // Strip control/space chars first so e.g. "java\tscript:" can't slip by.
      if (_ALLOWED_HTML_URL_ATTRS.has(name)) {
        if (name === 'srcset' ? _isDangerousSrcset(attr.value) : _isDangerousUrl(attr.value)) {
          el.removeAttribute(attr.name);
        }
      }
    }
  }
  return tpl.innerHTML;
}

function sanitizeAllowedHtml(html) {
  const raw = String(html == null ? '' : html);
  // Non-browser context (e.g. a future SSR/Node import): fail closed by
  // escaping rather than trusting the markup.
  if (typeof document === 'undefined') return escapeHtml(raw);

  // Sanitize to a fixpoint. Re-parsing the serialized output can mutate the
  // tree (the basis of mutation-XSS), so re-clean until it stops changing.
  let out = raw;
  for (let i = 0; i < 4; i++) {
    const next = _cleanAllowedHtmlOnce(out);
    if (next === out) break;
    out = next;
  }
  return out;
}

/**
 * Check if text has unclosed think tag
 */
export function hasUnclosedThinkTag(text) {
  text = text || '';
  const openCount =
    (text.match(/<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>/gi) || []).length
    + (text.match(/<\|channel>thought/gi) || []).length;
  const closeCount =
    (text.match(/<\/(?:think(?:ing)?|thought)>/gi) || []).length
    + (text.match(/<channel\|>/gi) || []).length;
  return openCount > closeCount;
}

export function startsWithReasoningPrefix(text) {
  return /^\s*(?:thinking(?:\s+process)?\s*:|the user |i need |i should |i will |they are |the question |i can )/i.test(text || '');
}

export function normalizeThinkingMarkup(text) {
  if (!text) return text;
  let normalized = text;
  normalized = normalized.replace(/<thought(\s+[^>]*)?>/gi, (_m, attrs = '') => `<think${attrs || ''}>`);
  normalized = normalized.replace(/<\/thought>/gi, '</think>');
  normalized = normalized.replace(/<\|channel>thought\s*\n?([\s\S]*?)<channel\|>\s*/gi, (_m, content = '') => {
    const thought = String(content || '').trim();
    return thought ? `<think>${thought}</think>\n` : '';
  });
  normalized = normalized.replace(/<\|channel>response\s*\n?([\s\S]*?)<channel\|>/gi, (_m, content = '') => content || '');
  normalized = normalized.replace(/<\|channel>response\s*\n?/gi, '');
  normalized = normalized.replace(/<channel\|>/gi, '');
  return normalized;
}

function normalizePlainThinking(text) {
  if (!text) return text;
  text = normalizeThinkingMarkup(text);
  if (/<think/i.test(text)) return text;

  const trimmed = text.trimStart();
  if (!startsWithReasoningPrefix(trimmed)) return text;

  const replyStarts = [
    'Hey', 'Hi ', 'Hi!', 'Hello', 'Sure', 'Yes', 'No ', 'No,', 'Yo', 'OK',
    'Here', 'Absolutely', 'Of course', 'Great', 'Alright', 'Thanks', 'Welcome',
    'Good ', "I'm happy", "I'd be"
  ];
  const prefixRegex = /^(thinking(?:\s+process)?\s*:)\s*/i;
  const escapedReplyStarts = replyStarts.map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const boundaryRegex = new RegExp(
    `^([\\s\\S]*?)(\\n\\n(?=${escapedReplyStarts.join('|')}|I |What|Let|This |As ))[\\s\\S]*$`,
    'i'
  );
  const boundaryMatch = boundaryRegex.exec(trimmed);

  if (boundaryMatch) {
    const thinkBlock = boundaryMatch[1].replace(prefixRegex, '').trim();
    const reply = trimmed.slice(boundaryMatch[1].length).trimStart();
    if (thinkBlock && reply) return `<think>${thinkBlock}</think>\n\n${reply}`;
  }

  const lines = trimmed.split('\n');
  for (let index = 1; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line) continue;
    if (replyStarts.some((prefix) => line.startsWith(prefix))) {
      const thinkBlock = lines.slice(0, index).join('\n').replace(prefixRegex, '').trim();
      const reply = lines.slice(index).join('\n').trim();
      if (thinkBlock && reply) return `<think>${thinkBlock}</think>\n${reply}`;
    }
  }

  const withoutPrefix = trimmed.replace(prefixRegex, '');
  for (const prefix of replyStarts) {
    const rx = new RegExp(`[.!?]\\s*(${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`);
    const match = rx.exec(withoutPrefix);
    if (match && match.index > 20) {
      const thinkBlock = withoutPrefix.slice(0, match.index + 1).trim();
      const reply = withoutPrefix.slice(match.index + 1).trim();
      if (thinkBlock && reply) return `<think>${thinkBlock}</think>\n${reply}`;
    }
  }

  return text;
}

/**
 * Extract all complete thinking blocks and remaining content
 */
export function extractThinkingBlocks(text) {
  // Handle malformed patterns: <think></think>\n...actual thinking...\n</think>
  // Some models emit an empty <think></think> then put thinking text outside,
  // closed by a second orphaned </think>.
  let normalized = normalizePlainThinking(text);
  // Collapse <think>short</think>...real thinking...</think> into one block
  // Models sometimes emit a trivial first block then continue thinking outside tags
  normalized = normalized.replace(/<think(?:ing)?(?:\s+[^>]*)?>.{0,30}<\/think(?:ing)?>\s*([\s\S]*?)<\/think(?:ing)?>/gi, (m, content) => {
    return '<think>' + content.trim() + '</think>';
  });

  // Merge consecutive <think> blocks (some models split thinking across multiple tags)
  normalized = normalized.replace(/<\/think(?:ing)?>\s*<think(?:ing)?(?:\s+[^>]*)?>/gi, '\n\n');

  // Extract thinking time attribute if present
  const timeMatch = normalized.match(/<think(?:ing)?\s+time="([\d.]+)"/i);
  const thinkingTime = timeMatch ? timeMatch[1] : null;
  // Strip time attribute for content extraction
  normalized = normalized.replace(/<think(?:ing)?\s+time="[\d.]+"/gi, '<think');

  const thinkRegex = /<think(?:ing)?(?:\s+[^>]*)?>([\s\S]*?)<\/think(?:ing)?>/gi;
  const thinkingBlocks = [];
  let match;

  // Extract all complete thinking blocks
  while ((match = thinkRegex.exec(normalized)) !== null) {
    const content = match[1].trim();
    if (content) thinkingBlocks.push(content);
  }

  // Remove all complete <think>/<thinking> blocks
  let cleanContent = normalized.replace(thinkRegex, '');

  // If there's an unclosed tag, decide between two cases:
  // (a) Stray opener at the very start with no real reply before it — typical
  //     of quantized models (MiniMax-AWQ) that emit a literal `<think>` token
  //     at the start of every reply without ever closing it. Strip just the
  //     opener and keep the body as the reply, otherwise the bubble looks
  //     blank on reload (the body was being treated as collapsed thinking).
  // (b) Cut-off mid-generation — there's already real reply text before the
  //     opener. Drop from the tag onward as before (it's truncated thinking).
  if (hasUnclosedThinkTag(normalized)) {
    const gemmaThoughtStart = cleanContent.search(/<\|channel>thought/i);
    if (gemmaThoughtStart >= 0) {
      const leakedThought = cleanContent
        .slice(gemmaThoughtStart)
        .replace(/^<\|channel>thought\s*\n?/i, '')
        .trim();
      if (gemmaThoughtStart === 0 && leakedThought) thinkingBlocks.push(leakedThought);
      cleanContent = cleanContent.slice(0, gemmaThoughtStart);
    } else {
      const strayOpener = cleanContent.match(/^\s*<think(?:ing)?(?:\s+[^>]*)?>([\s\S]*)$/i);
      if (strayOpener) {
        cleanContent = strayOpener[1];
      } else {
        cleanContent = cleanContent.replace(/<think(?:ing)?(?:\s+[^>]*)?>[\s\S]*$/gi, '');
      }
    }
  }

  // Handle orphaned </think> with no opening tag — text before it is leaked thinking
  const orphanMatch = cleanContent.match(/^([\s\S]+?)<\/think(?:ing)?>/i);
  if (orphanMatch && orphanMatch[1].trim()) {
    thinkingBlocks.push(orphanMatch[1].trim());
    cleanContent = cleanContent.slice(orphanMatch[0].length);
  }

  // Strip any remaining orphaned closing tags
  cleanContent = cleanContent.replace(/<\/think(?:ing)?>/gi, '');

  // Merge all thinking blocks into one — no reason to show multiple dropdowns
  const mergedBlocks = thinkingBlocks.length > 1
    ? [thinkingBlocks.join('\n\n')]
    : thinkingBlocks;

  return {
    thinkingBlocks: mergedBlocks,
    content: cleanContent.trim(),
    thinkingTime,
  };
}

/**
 * Create a collapsible thinking section
 */
function createThinkingSection(thinkingContent, index = 0, thinkingTime = null) {
  const id = `thinking-${Date.now()}-${index}`;
  const timeHtml = thinkingTime ? `<span style="font-size:11px;opacity:0.4;font-variant-numeric:tabular-nums;">${thinkingTime}s</span>` : '';
  return `
    <div class="thinking-section">
      <div class="thinking-header" data-thinking-id="${id}">
        <div class="thinking-header-left">
          <span>View thinking process</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          ${timeHtml}
          <span class="thinking-toggle" id="${id}-toggle"></span>
        </div>
      </div>
      <div class="thinking-content" id="${id}">
        <div class="thinking-content-inner">
          ${mdToHtml(thinkingContent)}
        </div>
      </div>
    </div>
  `;
}

/**
 * Process text and render with thinking sections
 */
// ── Emoji → monochrome SVG (OpenMoji-black via same-origin /api/emoji proxy) ──
// Replace colorful system/Twemoji emoji with single-color line icons tinted to
// the surrounding text color (project rule: never colorful emoji). Operates on
// rendered HTML: only touches text outside tags and skips <code>/<pre>.
const _EMOJI_RE = /\p{Extended_Pictographic}/u;
const _emojiSeg = (typeof Intl !== 'undefined' && Intl.Segmenter)
  ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null;

function _emojiCodepoints(emoji) {
  // Twemoji filename rule: strip U+FE0F unless the sequence has a ZWJ (U+200D).
  const s = emoji.indexOf('‍') >= 0 ? emoji : emoji.replace(/️/g, '');
  const cps = [];
  for (const ch of s) { const c = ch.codePointAt(0); if (c) cps.push(c.toString(16)); }
  return cps.join('-');
}
function _emojiImg(emoji) {
  const code = _emojiCodepoints(emoji);
  if (!code) return emoji;
  // Monochrome line icon: the OpenMoji black SVG is used as a CSS mask filled
  // with the surrounding text color (currentColor), so emoji render as a single
  // theme-tinted line glyph — never colorful (project rule). If the proxy can't
  // supply the glyph it returns a transparent SVG, so the mask shows nothing.
  return `<span class="emoji" role="img" aria-label="${emoji}" style="--em:url('/api/emoji/${code}.svg')"></span>`;
}
function _svgifyText(text) {
  if (!_emojiSeg) return text;
  let out = '';
  for (const { segment } of _emojiSeg.segment(text)) {
    out += _EMOJI_RE.test(segment) ? _emojiImg(segment) : segment;
  }
  return out;
}
/** When "Text-only Emojis" is on, keep Unicode in HTML so deEmojify() can strip them. */
function _useSvgEmoji() {
  return typeof document === 'undefined' || !document.body?.classList.contains('text-emojis');
}

// `opts.shortcodes` (default true) controls the issue-#345 `:name:` → emoji
// expansion. Chat passes it through as true; document/email body renderers pass
// false so author-typed `:shortcode:` text stays literal (see mdToHtml callers).
// The Unicode-emoji → monochrome-SVG pass always runs regardless, so a real 😀
// in a document still renders as the themed line icon as it always has.
export function svgifyEmoji(html, opts) {
  if (!_useSvgEmoji() || !html) return html;
  const allowShortcodes = !opts || opts.shortcodes !== false;
  // Two reasons to walk the HTML: real Unicode emoji to turn into SVG icons,
  // or `:shortcode:` text the model emitted instead of an emoji (issue #345).
  const hasUnicode = _EMOJI_RE.test(html);
  const hasShortcode = allowShortcodes && hasEmojiShortcode(html);
  if (!hasUnicode && !hasShortcode) return html;
  const parts = html.split(/(<[^>]*>)/);   // odd indices = tags
  let codeDepth = 0;
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      const t = parts[i].toLowerCase();
      if (/^<(pre|code)[\s>]/.test(t)) codeDepth++;
      else if (/^<\/(pre|code)\s*>/.test(t)) codeDepth = Math.max(0, codeDepth - 1);
      continue;
    }
    if (codeDepth !== 0) continue;
    let seg = parts[i];
    // Expand shortcodes to Unicode first, then both they and any pre-existing
    // Unicode emoji get rendered as the same monochrome line icons below.
    if (hasShortcode) seg = replaceEmojiShortcodes(seg);
    if (_EMOJI_RE.test(seg)) seg = _svgifyText(seg);
    parts[i] = seg;
  }
  return parts.join('');
}
/**
 * Generic collapsible section that reuses the thinking-dropdown styling and its
 * delegated toggle (any `.thinking-header[data-thinking-id]`). The label drives
 * the "View <label>" / "Hide <label>" text via data-label. Used e.g. for the
 * vision-model image description on a user's photo message.
 */
export function createCollapsible(contentMarkdown, label = 'details') {
  const id = `collapse-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const safeLabel = escapeHtml(label);
  return `
    <div class="thinking-section">
      <div class="thinking-header" data-thinking-id="${id}">
        <div class="thinking-header-left"><span data-label="${safeLabel}">View ${safeLabel}</span></div>
        <div style="display:flex;align-items:center;gap:6px;"><span class="thinking-toggle" id="${id}-toggle"></span></div>
      </div>
      <div class="thinking-content" id="${id}"><div class="thinking-content-inner">${mdToHtml(contentMarkdown)}</div></div>
    </div>`;
}

export function processWithThinking(text) {
  const { thinkingBlocks, content, thinkingTime } = extractThinkingBlocks(text);

  let html = '';

  // Add thinking sections (collapsed by default)
  thinkingBlocks.forEach((block, index) => {
    html += createThinkingSection(block, index, thinkingTime);
  });

  // Add the actual content
  if (content) {
    html += mdToHtml(content);
  }

  return _useSvgEmoji() ? svgifyEmoji(html) : html;
}

/**
 * Convert markdown to HTML
 */
export function mdToHtml(src, opts) {
  const allowedHtmlBlocks = [];
  const codeBlocks = [];
  const mermaidBlocks = [];
  const billingChartBlocks = [];
  let s = (src ?? '');

  // Extract fenced code blocks before any markdown/HTML preservation passes.
  // Otherwise placeholders from the allowed-HTML sanitizer (e.g.
  // ___ALLOWED_HTML_0___) can leak into quoted HTML/JS samples, because the
  // placeholder gets captured as literal code content and never restored inside
  // the final <pre><code> block.
  s = s.replace(/```([\w-]+)?\n([\s\S]*?)```/g, (_, lang, code) => {
    const cleaned = code
      .replace(/\r\n/g, '\n')
      .replace(/[ \t]+$/gm, '')
      .replace(/^\s*\n+/, '')
      .replace(/\n+\s*$/g, '');

    if (lang && lang.toLowerCase() === 'billing-chart') {
      const raw = cleaned.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
      const placeholder = `___BILLING_CHART_BLOCK_${billingChartBlocks.length}___`;
      billingChartBlocks.push(_billingChartHtml(raw));
      return placeholder;
    }

    // Mermaid diagrams: render as diagram instead of code block
    if (lang && lang.toLowerCase() === 'mermaid') {
      const mermaidId = 'mermaid-' + Date.now() + '-' + mermaidBlocks.length;
      const raw = cleaned.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
      const placeholder = `___MERMAID_BLOCK_${mermaidBlocks.length}___`;
      mermaidBlocks.push(`<div class="mermaid-container"><pre class="mermaid" id="${mermaidId}">${escapeHtml(raw)}</pre></div>`);
      return placeholder;
    }

    const escaped = cleaned.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    const placeholder = `___CODE_BLOCK_${codeBlocks.length}___`;

    const langClass = lang ? ` class="language-${lang}"` : '';
    const runnableLangs = ['python','py','javascript','js','html','bash','sh','shell','zsh'];
    const runBtn = (lang && runnableLangs.includes(lang.toLowerCase()))
      ? `<button type="button" class="run-code" data-code="${escapeHtml(escaped)}" data-lang="${lang}" title="Run code"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg></button>`
      : '';
    const editBtn = `<button type="button" class="edit-code" title="Edit"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>`;
    codeBlocks.push(`<pre><code${langClass} data-lang="${lang || ''}">${escapeHtml(escaped)}</code>${runBtn}${editBtn}<button type="button" class="copy-code" data-code="${escapeHtml(escaped)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button></pre>`);

    return placeholder;
  });

  // Repair common ways the agent mangles the entity-anchor convention
  // (`[Name](#kind-<id>)`). Models reliably get the single-link case
  // right but slip into other formats when listing many in a table.
  // These regexes upgrade the broken forms to proper markdown links so
  // the standard `[text](url)` handler below picks them up.
  const ANCHOR_KIND = '(?:session|document|note|image|email|event|task|skill|research)';
  // Case A: `[Name] [#kind-id]` — agent put the URL in brackets, often
  // in a table cell next to the label. Pair them.
  s = s.replace(
    new RegExp(`\\[([^\\]\\n]+?)\\]\\s*\\[#(${ANCHOR_KIND}-[A-Za-z0-9_-]+)\\]`, 'g'),
    '[$1](#$2)',
  );
  // Case B: bare `[#kind-id]` with no preceding label — give it a
  // generic "→ open" link text so it still renders as a button.
  s = s.replace(
    new RegExp(`\\[#(${ANCHOR_KIND}-[A-Za-z0-9_-]+)\\]`, 'g'),
    '[→ open](#$1)',
  );
  // Case C: bare `#kind-id` in plain text — only when it's word-
  // boundary delimited and NOT already inside a markdown link or
  // anchor syntax. Use a lookbehind for `](` or `[` to skip those.
  s = s.replace(
    new RegExp(`(^|[^\\[(])#(${ANCHOR_KIND}-[A-Za-z0-9_-]+)\\b`, 'g'),
    '$1[#$2](#$2)',
  );

  // Convert markdown links [text](url) to clickable links
  // Internal #hash links navigate in-page; external links open in new tab
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, url) => {
    return linkHtml(text, url);
  });

  // Autolink bare URLs (http/https). Skips URLs already inside <a> tags
  // (placed by markdown link replacement above) and URLs in backticks.
  s = s.replace(
    /(^|[\s(<])(https?:\/\/[^\s<>"'`\]]+[^\s<>"'`\].,;:!?])/g,
    (match, prefix, url) => `${prefix}${linkHtml(url, url)}`
  );

  // Autolink scheme-less domains the model often emits as plain text
  // (e.g. "techcrunch.com/ai", "perplexity.ai", "www.wired.com"). The TLD
  // allowlist keeps it from matching file names / versions ("package.json",
  // "node.js", "v1.2.3"); the required start/[\s(<] prefix means domains
  // already inside an http link (preceded by "//") or an email ("@") are
  // skipped. Require the TLD to end at a real domain boundary so dotted code
  // identifiers like `sklearn.metrics` do not link `sklearn.me` and leave
  // placeholder fragments in the remaining text.
  s = s.replace(
    /(^|[\s(<])((?:www\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|ai|co|dev|app|gov|edu|news|info|tech|xyz|me)(?=$|[\/\s<>"'`\]).,;:!?])(?:\/[^\s<>"'`\])]*)?)/gi,
    (match, prefix, domain) => {
      const trail = (domain.match(/[.,;:!?)]+$/) || [''])[0];
      const core = trail ? domain.slice(0, -trail.length) : domain;
      return `${prefix}${linkHtml(core, 'https://' + core)}${trail}`;
    }
  );

  // Extract <details>...</details> blocks and replace with placeholders
  // Default to open so agent output is visible
  s = s.replace(/<details>([\s\S]*?)<\/details>/gi, (match) => {
    const placeholder = `___ALLOWED_HTML_${allowedHtmlBlocks.length}___`;
    allowedHtmlBlocks.push(sanitizeAllowedHtml(match.replace(/<details>/i, '<details open>')));
    return placeholder;
  });

  // ALSO preserve <a> tags the same way (they're now in the HTML from markdown conversion)
  s = s.replace(/<a\s+[^>]*>.*?<\/a>/gi, (match) => {
    const placeholder = `___ALLOWED_HTML_${allowedHtmlBlocks.length}___`;
    allowedHtmlBlocks.push(sanitizeAllowedHtml(match));
    return placeholder;
  });

  // Now escape everything else
  s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  s = s.replace(/\n{3,}/g, '\n\n');

  // KaTeX math rendering (after code blocks are extracted, so math in code is safe)
  const mathBlocks = [];
  if (window.katex) {
    // Display math: \[ ... \]  — GPT-style delimiter (gpt-5.x, Claude, etc.).
    // Handle before $$/$ so all common delimiters render.
    s = s.replace(/\\\[([\s\S]*?)\\\]/g, (match, math) => {
      try {
        const raw = math.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        const placeholder = `___MATH_BLOCK_${mathBlocks.length}___`;
        mathBlocks.push(katex.renderToString(raw.trim(), { displayMode: true, throwOnError: false }));
        return placeholder;
      } catch (e) { return match; }
    });
    // Inline math: \( ... \)  — GPT-style inline delimiter. Single-line only
    // ([^\n]) so a stray escaped paren in prose can't swallow across lines.
    s = s.replace(/\\\(([^\n]*?)\\\)/g, (match, math) => {
      try {
        const raw = math.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        const placeholder = `___MATH_BLOCK_${mathBlocks.length}___`;
        mathBlocks.push(katex.renderToString(raw.trim(), { displayMode: false, throwOnError: false }));
        return placeholder;
      } catch (e) { return match; }
    });
    // Display math: $$...$$
    s = s.replace(/\$\$([\s\S]*?)\$\$/g, (match, math) => {
      try {
        const raw = math.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        const placeholder = `___MATH_BLOCK_${mathBlocks.length}___`;
        mathBlocks.push(katex.renderToString(raw.trim(), { displayMode: true, throwOnError: false }));
        return placeholder;
      } catch (e) { return match; }
    });
    // Inline math: $...$  (not preceded/followed by $ or digit, not spanning multiple lines)
    s = s.replace(/(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)/g, (match, math) => {
      try {
        const raw = math.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        const placeholder = `___MATH_BLOCK_${mathBlocks.length}___`;
        mathBlocks.push(katex.renderToString(raw.trim(), { displayMode: false, throwOnError: false }));
        return placeholder;
      } catch (e) { return match; }
    });
  }

  // Handle pipe tables
  s = s.replace(/(?:^|\n)([^\n]*\|[^\n]*\|[^\n]*)(?:\n([^\n]*\|[^\n]*\|[^\n]*))*/g, (table) => {
    if (table.includes('___CODE_BLOCK_') || table.includes('___ALLOWED_HTML_')) return table;

    const rows = table.trim().split('\n');
    if (rows.length < 2) return table;

    let html = '<table style="border-collapse: collapse; width: 100%; margin: 10px 0;">';

    rows.forEach((row, idx) => {
      if (idx === 1 && /^[\s|:\-]+$/.test(row)) {
        html += '<tbody>';
        return;
      }
      const cells = splitTableRow(row);
      if (cells.length === 0) return;

      html += '<tr>';

      cells.forEach(cell => {
        const tag = idx === 0 ? 'th' : 'td';
        html += `<${tag} style="padding: 8px; text-align: left; border-bottom: 1px solid var(--border);">${cell.trim()}</${tag}>`;
      });

      html += '</tr>';
    });

    html += '</tbody></table>';
    return html;
  });

  // Inline code (but not placeholders)
  s = s.replace(/`([^`]+?)`/g, (match, code) => {
    if (code.startsWith('___CODE_BLOCK_') || code.startsWith('___ALLOWED_HTML_')) return match;
    return `<code>${code}</code>`;
  });

  // Horizontal rules (must come before bold/italic to avoid * conflicts)
  s = s.replace(/^(?:---|\*\*\*|___)\s*$/gm, '<hr>');

  // Bold, italic, strikethrough
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\*([^*]+)\*/g, '<em>$1</em>');
  s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');

  // Headers
  s = s.replace(/^###### (.*)$/gm, '<h6>$1</h6>')
       .replace(/^##### (.*)$/gm, '<h5>$1</h5>')
       .replace(/^#### (.*)$/gm, '<h4>$1</h4>')
       .replace(/^### (.*)$/gm, '<h3>$1</h3>')
       .replace(/^## (.*)$/gm, '<h2>$1</h2>')
       .replace(/^# (.*)$/gm, '<h1>$1</h1>');

  // Ordered lists (1. 2. 3. etc.)
  s = s.replace(/^(\d+)\. (.*)$/gm, '<oli>$2</oli>');
  s = s.replace(/(?:^|\n)(<oli>[\s\S]*?)(?=\n(?!<oli>)|$)/g, m => `<ol>${m.trim().replace(/<\/?oli>/g, (t) => t === '<oli>' ? '<li>' : '</li>')}</ol>`);

  // Unordered lists
  s = s.replace(/^(?:- |\* )(.*)$/gm, '<uli>$1</uli>');
  s = s.replace(/(^|\n)((?:<uli>[^\n]*<\/uli>(?:\n|$))+)/g, (_, prefix, block) =>
    `${prefix}<ul>${block.trim().replace(/<\/?uli>/g, (t) => t === '<uli>' ? '<li>' : '</li>')}</ul>`);

  // Blockquotes
  s = s.replace(/^&gt; (.*)$/gm, '<bq>$1</bq>');
  s = s.replace(/(?:^|\n)(<bq>[\s\S]*?)(?=\n(?!<bq>)|$)/g, m =>
    `<blockquote>${m.trim().replace(/<\/?bq>/g, (t) => t === '<bq>' ? '<p>' : '</p>')}</blockquote>`);

  // Paragraphs - but NOT for code block placeholders or allowed HTML
  s = s.replace(/^(?!<h\d|<ul>|<ol>|<li>|<oli>|<pre>|<blockquote>|<bq>|<hr>|___CODE_BLOCK_|___ALLOWED_HTML_|___MATH_BLOCK_|___MERMAID_BLOCK_|___BILLING_CHART_BLOCK_)([^\n]+)$/gm, '<p>$1</p>');

  // Line breaks within paragraphs
  s = s.replace(/<p>([\s\S]*?)<\/p>/g, (match, content) => {
    if (content.includes('___CODE_BLOCK_') || content.includes('___ALLOWED_HTML_') || content.includes('___MATH_BLOCK_') || content.includes('___MERMAID_BLOCK_') || content.includes('___BILLING_CHART_BLOCK_')) return match;
    const withLineBreaks = content.replace(/\n{2,}/g, '</p><p>').replace(/\n/g, '<br>');
    return `<p>${withLineBreaks}</p>`;
  });

  // Remove empty paragraphs
  s = s.replace(/<p><\/p>/g, '');

  // CRITICAL: Restore allowed HTML blocks first
  allowedHtmlBlocks.forEach((block, index) => {
    s = s.replace(`___ALLOWED_HTML_${index}___`, block);
  });

  // Restore math blocks
  mathBlocks.forEach((block, index) => {
    s = s.replace(`___MATH_BLOCK_${index}___`, block);
  });

  // Restore mermaid diagram blocks
  mermaidBlocks.forEach((block, index) => {
    s = s.replace(`___MERMAID_BLOCK_${index}___`, block);
  });

  billingChartBlocks.forEach((block, index) => {
    s = s.replace(`___BILLING_CHART_BLOCK_${index}___`, block);
  });

  // CRITICAL: Restore code blocks at the end
  codeBlocks.forEach((block, index) => {
    s = s.replace(`___CODE_BLOCK_${index}___`, block);
  });

  return _useSvgEmoji() ? svgifyEmoji(s, opts) : s;
}

/**
 * Reduce excessive whitespace outside of code blocks
 */
export function squashOutsideCode(s) {
  if (!s) return "";
  const parts = String(s).split(/```/);
  for (let i = 0; i < parts.length; i += 2) {
    parts[i] = parts[i]
      .replace(/\r\n/g, '\n')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n');
  }
  return parts.join('```');
}

/**
 * Render content that may be text or array of content blocks
 */
export function renderContent(content) {
  if (Array.isArray(content)) {
    const texts = [];
    for (const blk of content) {
      if (blk.type === 'text') texts.push(blk.text);
      else if (blk.type === 'image_url') texts.push('[image]');
    }
    return texts.join('\n');
  }
  return content;
}

/**
 * Initialize any unprocessed Mermaid diagrams in a container (or whole document)
 */
export function renderMermaid(container) {
  if (!window.mermaid) return;
  initMermaid();
  const target = container || document;
  const pending = target.querySelectorAll('pre.mermaid:not([data-processed])');
  if (pending.length === 0) return;
  try {
    window.mermaid.run({ nodes: pending });
  } catch (e) {
    console.warn('Mermaid render error:', e);
  }
}

const markdownModule = {
  escapeHtml,
  mdToHtml,
  squashOutsideCode,
  renderContent,
  processWithThinking,
  createCollapsible,
  hasUnclosedThinkTag,
  extractThinkingBlocks,
  normalizeThinkingMarkup,
  startsWithReasoningPrefix,
  renderMermaid
};

export default markdownModule;

// Mermaid is loaded async so it cannot delay the app shell.
function initMermaid() {
  if (!window.mermaid || window.__odysseusMermaidReady) return;
  window.mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose' });
  window.__odysseusMermaidReady = true;
}
window.odysseusInitMermaid = initMermaid;
initMermaid();

const BILLING_CHART_SNAP_RADIUS_PX = 38;
let _billingChartSnapFrame = null;

function _billingChartClearSnap(frame) {
  if (!frame) return;
  frame.querySelectorAll('.billing-chart-point.snap-active').forEach(point => {
    point.classList.remove('snap-active');
  });
}

function _billingChartSnapPoint(frame, clientX, clientY) {
  if (!frame) return;
  const points = Array.from(frame.querySelectorAll('.billing-chart-point'));
  let nearest = null;
  let nearestDistance = Infinity;
  for (const point of points) {
    const style = window.getComputedStyle ? window.getComputedStyle(point) : null;
    if (style && (style.display === 'none' || style.visibility === 'hidden')) continue;
    const rect = point.getBoundingClientRect();
    if (!rect.width && !rect.height) continue;
    const x = rect.left + (rect.width / 2);
    const y = rect.top + (rect.height / 2);
    const distance = Math.hypot(clientX - x, clientY - y);
    if (distance < nearestDistance) {
      nearest = point;
      nearestDistance = distance;
    }
  }

  if (!nearest || nearestDistance > BILLING_CHART_SNAP_RADIUS_PX) {
    _billingChartClearSnap(frame);
    return;
  }

  points.forEach(point => point.classList.toggle('snap-active', point === nearest));
}

function _billingChartToggleProjection(input) {
  const plot = input?.closest?.('.billing-chart-plot') || null;
  if (!plot) return;
  plot.classList.toggle('show-projected', !!input.checked);
  _billingChartClearSnap(plot.querySelector('.billing-chart-plot-frame'));
}

function _billingChartToggleThresholds(input) {
  const plot = input?.closest?.('.billing-chart-plot') || null;
  if (!plot) return;
  plot.classList.toggle('show-thresholds', !!input.checked);
}

function _billingChartSetLoadError(card, message) {
  if (!card) return;
  let error = card.querySelector('.billing-chart-load-error');
  if (!error) {
    error = document.createElement('div');
    error.className = 'billing-chart-load-error';
    card.appendChild(error);
  }
  error.textContent = message;
}

async function _billingChartSwitchMonth(button) {
  const targetMonth = String(button?.getAttribute?.('data-billing-chart-month') || '').trim();
  if (!/^\d{4}-\d{2}$/.test(targetMonth) || button.disabled) return;
  const card = button.closest?.('.billing-chart-card') || null;
  if (!card || card.classList.contains('billing-chart-loading')) return;

  const params = new URLSearchParams();
  params.set('period', 'month');
  params.set('month', targetMonth);
  params.set('group_by', card.getAttribute('data-billing-group-by') || 'provider');

  const provider = String(card.getAttribute('data-billing-provider-query') || '').trim();
  const spendSource = String(card.getAttribute('data-billing-spend-source') || '').trim();
  const spendScope = String(card.getAttribute('data-billing-spend-scope') || '').trim();
  if (provider) params.set('provider', provider);
  if (spendSource) params.set('spend_source', spendSource);
  if (spendScope) params.set('spend_scope', spendScope);

  card.classList.add('billing-chart-loading');
  try {
    const response = await fetch(`/api/billing/spending-graph?${params.toString()}`, {
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`Billing graph request failed (${response.status})`);
    const payload = await response.json();
    if (!payload?.chart || payload.chart.kind !== 'billing-spend') {
      throw new Error('Billing graph response did not include chart data');
    }
    const template = document.createElement('template');
    template.innerHTML = _billingChartHtml(JSON.stringify(payload.chart)).trim();
    const nextCard = template.content.firstElementChild;
    if (!nextCard) throw new Error('Billing graph response could not be rendered');
    card.replaceWith(nextCard);
  } catch (error) {
    card.classList.remove('billing-chart-loading');
    _billingChartSetLoadError(card, error?.message || 'Billing graph could not be loaded');
  }
}

function _billingChartFrameForPointer(target, clientX, clientY) {
  const direct = target.closest?.('.billing-chart-plot-frame') || null;
  if (direct) return direct;
  for (const frame of document.querySelectorAll('.billing-chart-plot-frame')) {
    const rect = frame.getBoundingClientRect();
    if (
      clientX >= rect.left - BILLING_CHART_SNAP_RADIUS_PX
      && clientX <= rect.right + BILLING_CHART_SNAP_RADIUS_PX
      && clientY >= rect.top - BILLING_CHART_SNAP_RADIUS_PX
      && clientY <= rect.bottom + BILLING_CHART_SNAP_RADIUS_PX
    ) {
      return frame;
    }
  }
  return null;
}

document.addEventListener('pointermove', function(e) {
  const frame = _billingChartFrameForPointer(e.target, e.clientX, e.clientY);
  if (_billingChartSnapFrame && _billingChartSnapFrame !== frame) {
    _billingChartClearSnap(_billingChartSnapFrame);
  }
  _billingChartSnapFrame = frame;
  if (!frame) return;
  _billingChartSnapPoint(frame, e.clientX, e.clientY);
});

document.addEventListener('pointerout', function(e) {
  const frame = e.target.closest?.('.billing-chart-plot-frame') || null;
  if (!frame) return;
  if (e.relatedTarget && frame.contains(e.relatedTarget)) return;
  _billingChartClearSnap(frame);
  if (_billingChartSnapFrame === frame) _billingChartSnapFrame = null;
});

document.addEventListener('change', function(e) {
  const projectionInput = e.target.closest?.('.billing-chart-projection-input') || null;
  if (projectionInput) {
    _billingChartToggleProjection(projectionInput);
    return;
  }
  const thresholdInput = e.target.closest?.('.billing-chart-threshold-input') || null;
  if (thresholdInput) {
    _billingChartToggleThresholds(thresholdInput);
  }
});

document.addEventListener('click', function(e) {
  const button = e.target.closest?.('.billing-chart-month-button') || null;
  if (!button) return;
  e.preventDefault();
  _billingChartSwitchMonth(button);
});

// Persist which thinking sections were expanded across page refreshes.
// IDs are render-generated (Date.now-based) so we key by a stable hash of
// the inner text content instead — same content reproduces the same hash on
// reload. LocalStorage holds a Set of expanded hashes; we observe the chat
// history and re-expand matching sections as they're inserted.
const THINK_EXPANDED_KEY = 'odysseus-thinking-expanded';
function _loadExpandedSet() {
  try { return new Set(JSON.parse(localStorage.getItem(THINK_EXPANDED_KEY) || '[]')); }
  catch { return new Set(); }
}
function _saveExpandedSet(set) {
  try {
    const arr = [...set];
    // Bound storage growth — keep the most recent 200 entries.
    if (arr.length > 200) arr.splice(0, arr.length - 200);
    localStorage.setItem(THINK_EXPANDED_KEY, JSON.stringify(arr));
  } catch {}
}
function _hashThinkingContent(el) {
  if (!el) return '';
  const text = (el.textContent || '').trim();
  if (!text) return '';
  let h = 0;
  for (let i = 0; i < text.length; i++) {
    h = (h * 31 + text.charCodeAt(i)) | 0;
  }
  return String(h);
}
function _setThinkingExpanded(content, toggle, header, expanded) {
  if (!content || !toggle) return;
  content.classList.toggle('expanded', expanded);
  toggle.classList.toggle('expanded', expanded);
  const label_el = header?.querySelector('.thinking-header-left span');
  if (label_el) {
    const label = label_el.dataset.label || 'thinking process';
    label_el.textContent = expanded ? `Hide ${label}` : `View ${label}`;
  }
}

// Delegated click handler for thinking toggle (CSP-safe, no inline onclick)
document.addEventListener('click', function(e) {
  const header = e.target.closest('.thinking-header[data-thinking-id]');
  if (!header) return;
  const id = header.dataset.thinkingId;
  const content = document.getElementById(id);
  const toggle = document.getElementById(id + '-toggle');
  if (!content || !toggle) return;

  const willExpand = !content.classList.contains('expanded');
  _setThinkingExpanded(content, toggle, header, willExpand);

  // Persist by content hash so the choice survives a refresh.
  const hash = _hashThinkingContent(content);
  if (!hash) return;
  const set = _loadExpandedSet();
  if (willExpand) set.add(hash);
  else set.delete(hash);
  _saveExpandedSet(set);
});

// Watch the chat history; whenever a thinking section appears, expand it if
// its hash matches one the user previously expanded.
(function _watchThinking() {
  if (window._thinkingWatcherWired) return;
  window._thinkingWatcherWired = true;
  const _apply = (root) => {
    if (!root || !root.querySelectorAll) return;
    const sections = root.matches?.('.thinking-section')
      ? [root]
      : [...root.querySelectorAll('.thinking-section')];
    if (!sections.length) return;
    const set = _loadExpandedSet();
    if (!set.size) return;
    for (const sec of sections) {
      const content = sec.querySelector('.thinking-content');
      if (!content) continue;
      if (content.classList.contains('expanded')) continue;
      const hash = _hashThinkingContent(content);
      if (!hash || !set.has(hash)) continue;
      const header = sec.querySelector('.thinking-header[data-thinking-id]');
      const id = header?.dataset.thinkingId;
      const toggle = id ? document.getElementById(id + '-toggle') : null;
      _setThinkingExpanded(content, toggle, header, true);
    }
  };
  const start = () => {
    const root = document.body;
    if (!root) return;
    _apply(root);
    new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType === 1) _apply(node);
        }
      }
    }).observe(root, { childList: true, subtree: true });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
