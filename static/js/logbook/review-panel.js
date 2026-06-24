import { iconBook, logbookIcon } from './icons.js';
import { escapeHtml as _e } from './utils.js';

function numberText(value, fallback = '0') {
  const num = Number(value);
  return Number.isFinite(num) ? num.toLocaleString() : fallback;
}

function averageText(summary) {
  const value = Number(summary?.average);
  return Number.isFinite(value) ? value.toFixed(value % 1 === 0 ? 0 : 1) : 'No data';
}

function rangeText(range = {}) {
  const start = range.start || '';
  const end = range.end || '';
  if (!start && !end) return '';
  return start === end ? start : `${start} - ${end}`;
}

function latestValueText(item) {
  const value = item?.latest_value;
  if (value === null || value === undefined || value === '') return '';
  const unit = item?.unit ? ` ${item.unit}` : '';
  return `${value}${unit}`;
}

function statHtml(label, value, hint = '') {
  return `
    <div class="logbook-review-stat">
      <span>${_e(label)}</span>
      <strong>${_e(value)}</strong>
      ${hint ? `<em>${_e(hint)}</em>` : ''}
    </div>
  `;
}

function scoreHtml(label, summary) {
  const count = Number(summary?.count || 0);
  return `
    <div class="logbook-review-score">
      <span>${_e(label)}</span>
      <strong>${_e(averageText(summary))}</strong>
      <em>${count ? `${count} day${count === 1 ? '' : 's'}` : 'No entries'}</em>
    </div>
  `;
}

function evidenceValueText(item) {
  const value = item?.value;
  if (value === null || value === undefined || value === '') return '';
  const unit = item?.unit || '';
  if (!unit) return String(value);
  return unit.startsWith('/') ? `${value}${unit}` : `${value} ${unit}`;
}

function insightLevelText(level) {
  if (level === 'warning') return 'Watch';
  if (level === 'positive') return 'Pattern';
  return 'Notice';
}

function insightEvidenceHtml(items = []) {
  if (!items.length) return '';
  const rows = items.slice(0, 3).map(item => {
    const label = [item.label || '', evidenceValueText(item)].filter(Boolean).join(' ');
    const body = `
      <span>${_e(item.date || '')}</span>
      ${label ? `<strong>${_e(label)}</strong>` : ''}
      ${item.snippet ? `<em>${_e(item.snippet)}</em>` : ''}
    `;
    if (item.date) {
      return `<button type="button" class="logbook-review-evidence" data-date="${_e(item.date)}">${body}</button>`;
    }
    return `<div class="logbook-review-evidence">${body}</div>`;
  }).join('');
  return `<div class="logbook-review-evidence-list">${rows}</div>`;
}

function insightsHtml(insights = []) {
  if (!insights.length) return '<div class="logbook-empty">No insight cards for this range yet.</div>';
  return `
    <div class="logbook-review-insights">
      ${insights.slice(0, 6).map(item => `
        <div class="logbook-review-insight" data-level="${_e(item.level || 'notice')}">
          <div class="logbook-review-insight-head">
            <strong>${_e(item.title || 'Insight')}</strong>
            <span>${_e(insightLevelText(item.level))}</span>
          </div>
          ${item.detail ? `<p>${_e(item.detail)}</p>` : ''}
          ${insightEvidenceHtml(item.evidence || [])}
        </div>
      `).join('')}
    </div>
  `;
}

function moodRowsHtml(moods = []) {
  if (!moods.length) return '<div class="logbook-empty">No mood labels in this range.</div>';
  const max = Math.max(1, ...moods.map(item => Number(item.count || 0)));
  return moods.map(item => {
    const count = Number(item.count || 0);
    const width = Math.max(6, Math.round((count / max) * 100));
    return `
      <div class="logbook-review-bar-row">
        <span>${_e(item.label || 'Mood')}</span>
        <div><i style="width:${width}%"></i></div>
        <strong>${_e(numberText(count))}</strong>
      </div>
    `;
  }).join('');
}

function datapointsHtml(datapoints = []) {
  if (!datapoints.length) return '<div class="logbook-empty">No datapoints in this range.</div>';
  return datapoints.slice(0, 6).map(item => {
    const latest = latestValueText(item);
    const avg = Number(item.numeric_count || 0) ? `avg ${numberText(item.average)}` : '';
    const meta = [latest ? `latest ${latest}` : '', avg, item.count ? `${item.count} entries` : ''].filter(Boolean).join(' | ');
    return `
      <div class="logbook-review-row">
        <strong>${_e(item.label || item.key || 'Data')}</strong>
        ${meta ? `<span>${_e(meta)}</span>` : ''}
      </div>
    `;
  }).join('');
}

function entityRowsHtml(items = [], { kind = 'person' } = {}) {
  if (!items.length) return `<div class="logbook-empty">No ${kind === 'person' ? 'people' : 'places'} in this range.</div>`;
  return items.slice(0, 6).map(item => {
    const label = item.display_name || item.name || (kind === 'person' ? 'Person' : 'Place');
    const bits = [
      item.count ? `${item.count} day${Number(item.count) === 1 ? '' : 's'}` : '',
      item.relationship_label || item.location_type || '',
      item.last_mentioned || '',
    ].filter(Boolean);
    return `
      <div class="logbook-review-row">
        <strong>${logbookIcon(kind === 'person' ? 'person' : 'location', 12)}${_e(label)}</strong>
        ${bits.length ? `<span>${_e(bits.join(' | '))}</span>` : ''}
      </div>
    `;
  }).join('');
}

function reconnectHtml(items = []) {
  if (!items.length) return '<div class="logbook-empty">No reconnect prompts right now.</div>';
  return items.slice(0, 4).map(item => `
    <div class="logbook-review-row">
      <strong>${logbookIcon('person', 12)}${_e(item.display_name || 'Person')}</strong>
      <span>${_e(item.message || item.last_mentioned || '')}</span>
    </div>
  `).join('');
}

function highlightsHtml(items = []) {
  if (!items.length) return '<div class="logbook-empty">No entry snippets in this range.</div>';
  return items.slice(0, 5).map(item => {
    const meta = [
      item.mood_label || '',
      ...(item.people || []).slice(0, 2),
      ...(item.places || []).slice(0, 2),
    ].filter(Boolean).join(' | ');
    return `
      <button type="button" class="logbook-review-highlight" data-date="${_e(item.date || '')}">
        <span><strong>${_e(item.date || '')}</strong>${meta ? `<em>${_e(meta)}</em>` : ''}</span>
        <span>${_e(item.snippet || item.title || '')}</span>
      </button>
    `;
  }).join('');
}

export function renderReviewPanelHtml({ review, busy = false, error = '', period = 'week' } = {}) {
  const data = review || {};
  const range = data.range || {};
  const stats = data.stats || {};
  const selected = period === 'month' ? 'month' : 'week';
  const empty = !busy && !error && !Number(stats.entry_count || 0);
  return `
    <div class="logbook-section-head">
      <h5>${iconBook(13)}<span>Review</span></h5>
      <div class="logbook-editor-toggle" role="group" aria-label="Review range">
        <button type="button" class="${selected === 'week' ? 'active' : ''}" data-logbook-review-period="week">Week</button>
        <button type="button" class="${selected === 'month' ? 'active' : ''}" data-logbook-review-period="month">Month</button>
      </div>
    </div>
    ${rangeText(range) ? `<div class="logbook-review-range">${_e(rangeText(range))}</div>` : ''}
    ${busy ? '<div class="logbook-empty">Loading review...</div>' : ''}
    ${error ? `<div class="logbook-ai-error">${_e(error)}</div>` : ''}
    ${empty ? '<div class="logbook-empty">No entries in this range yet.</div>' : ''}
    <div class="logbook-review">
      <div class="logbook-review-stats">
        ${statHtml('Entries', numberText(stats.entry_count))}
        ${statHtml('Days', `${numberText(stats.days_with_entries)}/${numberText(stats.range_days)}`)}
        ${statHtml('People', numberText(stats.people_count))}
        ${statHtml('Places', numberText(stats.place_count))}
        ${statHtml('Data', numberText(stats.datapoint_count))}
      </div>
      <div class="logbook-review-scores">
        ${scoreHtml('Mood', data.scores?.mood)}
        ${scoreHtml('Energy', data.scores?.energy)}
        ${scoreHtml('Stress', data.scores?.stress)}
      </div>
      <section class="logbook-review-section">
        <h6>Insights</h6>
        ${insightsHtml(data.insights || [])}
      </section>
      <section class="logbook-review-section">
        <h6>Moods</h6>
        ${moodRowsHtml(data.moods || [])}
      </section>
      <section class="logbook-review-section">
        <h6>Datapoints</h6>
        ${datapointsHtml(data.datapoints || [])}
      </section>
      <section class="logbook-review-split">
        <div class="logbook-review-section">
          <h6>People</h6>
          ${entityRowsHtml(data.top_people || [], { kind: 'person' })}
        </div>
        <div class="logbook-review-section">
          <h6>Places</h6>
          ${entityRowsHtml(data.top_places || [], { kind: 'location' })}
        </div>
      </section>
      <section class="logbook-review-section">
        <h6>Reconnect</h6>
        ${reconnectHtml(data.reconnect_candidates || [])}
      </section>
      <section class="logbook-review-section">
        <h6>Highlights</h6>
        <div class="logbook-review-highlights">${highlightsHtml(data.highlights || [])}</div>
      </section>
    </div>
  `;
}
