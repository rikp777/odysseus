import { listEntries } from '../logbook/api.js';
import { iconBook } from '../logbook/icons.js';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MARKER_CLASS = 'custom-logbook-calendar-marker';
const HAS_ENTRY_CLASS = 'custom-logbook-has-entry';

let refreshTimer = null;
let requestId = 0;
let applyingMarkers = false;
const rangeCache = new Map();

function calendarBody() {
  const modal = document.getElementById('calendar-modal');
  if (!modal || modal.classList.contains('hidden')) return null;
  return modal.querySelector('#cal-body');
}

function markerCells(body) {
  return Array.from(body.querySelectorAll('.cal-day[data-date], .cal-wk-col[data-date], .cal-year-day[data-date]'))
    .filter(cell => DATE_RE.test(cell.dataset.date || ''));
}

function markerHost(cell) {
  if (cell.classList.contains('cal-wk-col')) {
    return cell.querySelector(':scope > .cal-wk-col-head') || cell;
  }
  return cell;
}

function visibleDateRange(cells) {
  const dates = [...new Set(cells.map(cell => cell.dataset.date).filter(date => DATE_RE.test(date || '')))].sort();
  if (!dates.length) return null;
  return { start: dates[0], end: dates[dates.length - 1], key: `${dates[0]}:${dates[dates.length - 1]}` };
}

function entryLabel(entry) {
  return entry?.title || entry?.summary || entry?.snippet || 'Logbook entry';
}

function titleFor(date, entries) {
  const count = entries.length;
  const prefix = `${count} Logbook ${count === 1 ? 'entry' : 'entries'} on ${date}`;
  const labels = entries.map(entryLabel).filter(Boolean).slice(0, 3);
  return labels.length ? `${prefix}: ${labels.join(' | ')}` : prefix;
}

async function openLogbookDate(date) {
  const module = window.logbookModule || (await import('../logbook.js')).default;
  if (module?.openLogbookDate) {
    await module.openLogbookDate(date);
    return;
  }
  await module?.openLogbook?.();
}

function markerButton(date, entries) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = MARKER_CLASS;
  button.dataset.logbookDate = date;
  button.title = titleFor(date, entries);
  button.setAttribute('aria-label', `Open Logbook for ${date}`);
  button.innerHTML = `${iconBook(10)}${entries.length > 1 ? `<span>${entries.length}</span>` : ''}`;
  button.addEventListener('pointerdown', event => {
    event.preventDefault();
    event.stopPropagation();
  });
  button.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    openLogbookDate(date).catch(err => console.debug('Failed to open Logbook date', err));
  });
  return button;
}

function clearMarkers(body) {
  body.querySelectorAll(`.${MARKER_CLASS}`).forEach(marker => marker.remove());
  body.querySelectorAll(`.${HAS_ENTRY_CLASS}`).forEach(cell => {
    cell.classList.remove(HAS_ENTRY_CLASS);
    if ('logbookCalendarTitle' in cell.dataset) {
      cell.title = cell.dataset.logbookCalendarTitle;
      delete cell.dataset.logbookCalendarTitle;
    }
  });
}

function applyMarkers(entriesByDate) {
  const body = calendarBody();
  if (!body) return;
  applyingMarkers = true;
  try {
    clearMarkers(body);
    markerCells(body).forEach(cell => {
      const date = cell.dataset.date;
      const entries = entriesByDate.get(date) || [];
      if (!entries.length) return;
      cell.classList.add(HAS_ENTRY_CLASS);
      cell.dataset.logbookCalendarTitle = cell.title || '';
      cell.title = titleFor(date, entries);
      if (cell.classList.contains('cal-year-day')) return;
      markerHost(cell).appendChild(markerButton(date, entries));
    });
  } finally {
    requestAnimationFrame(() => { applyingMarkers = false; });
  }
}

async function entriesForRange(start, end) {
  const key = `${start}:${end}`;
  if (rangeCache.has(key)) return rangeCache.get(key);
  const params = new URLSearchParams({ start, end });
  const data = await listEntries(params);
  const entriesByDate = new Map();
  (data.entries || []).forEach(entry => {
    const date = entry?.entry_date;
    if (!DATE_RE.test(date || '')) return;
    if (!entriesByDate.has(date)) entriesByDate.set(date, []);
    entriesByDate.get(date).push(entry);
  });
  rangeCache.set(key, entriesByDate);
  return entriesByDate;
}

async function refreshMarkers() {
  const body = calendarBody();
  if (!body) return;
  const cells = markerCells(body);
  const range = visibleDateRange(cells);
  if (!range) return;
  const currentRequest = ++requestId;
  try {
    const entriesByDate = await entriesForRange(range.start, range.end);
    if (currentRequest !== requestId) return;
    applyMarkers(entriesByDate);
  } catch (err) {
    console.debug('Failed to load Logbook calendar markers', err);
  }
}

function scheduleRefresh({ clearCache = false } = {}) {
  if (clearCache) rangeCache.clear();
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    refreshMarkers();
  }, 80);
}

const observer = new MutationObserver(() => {
  if (applyingMarkers) return;
  if (!calendarBody()) return;
  scheduleRefresh();
});

observer.observe(document.body, { childList: true, subtree: true });
window.addEventListener('calendar-refresh', () => scheduleRefresh({ clearCache: true }));
window.addEventListener('logbook-entries-refresh', () => scheduleRefresh({ clearCache: true }));
window.addEventListener('focus', () => scheduleRefresh({ clearCache: true }));
scheduleRefresh();
