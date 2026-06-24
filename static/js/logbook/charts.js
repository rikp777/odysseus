/**
 * Reusable SVG line chart primitives for logbook panels.
 *
 * Public API:
 *   renderLineChart(opts)  → <svg>...</svg> string
 *   renderChartLegend(items) → legend HTML string
 *   build14DayWindow(todayFn, dateAddFn) → { days, today }
 */

const _DOW = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

function _esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function _buildPath(days, getVal, xPos, yPos) {
  let d = '', open = false;
  days.forEach((date, i) => {
    const v = getVal(date, i);
    if (v == null) { open = false; return; }
    const x = xPos(i).toFixed(1), y = yPos(v).toFixed(1);
    d += open ? ` L${x},${y}` : `M${x},${y}`;
    open = true;
  });
  return d;
}

function _buildDots(days, today, getVal, getLabel, seriesLabel, color, xPos, yPos, rNormal, rToday) {
  return days.map((date, i) => {
    const v = getVal(date, i);
    if (v == null) return '';
    const isToday = date === today;
    return `<circle cx="${xPos(i).toFixed(1)}" cy="${yPos(v).toFixed(1)}" r="${isToday ? rToday : rNormal}" fill="${color}" stroke="var(--panel)" stroke-width="1.5" data-chart-dot data-chart-date="${_esc(date)}" data-chart-val="${_esc(getLabel(date, v))}" data-chart-series="${_esc(seriesLabel)}"></circle>`;
  }).join('');
}

function _buildXLabels(days, xPos, vh) {
  const n = days.length - 1;
  return days.map((d, i) => {
    const dow = new Date(d + 'T00:00:00').getDay();
    if (dow !== 1 && dow !== 4 && i !== 0 && i !== n) return '';
    return `<text x="${xPos(i).toFixed(1)}" y="${vh - 3}" text-anchor="middle" font-size="9" fill="var(--fg)" opacity="0.38">${_DOW[dow]} ${d.slice(8)}</text>`;
  }).join('');
}

function _buildYGrid(ticks, yPos, yTickLabels, vw, pl, pr) {
  return ticks.map(v => {
    const y = yPos(v).toFixed(1);
    const lbl = yTickLabels?.[v];
    const text = lbl ? `<text x="${pl - 4}" y="${y}" text-anchor="end" dominant-baseline="middle" font-size="9" fill="var(--fg)" opacity="0.38">${_esc(lbl)}</text>` : '';
    const isOdd = Number.isInteger(v) && v % 2 === 1;
    return `<line x1="${pl}" y1="${y}" x2="${vw - pr}" y2="${y}" stroke="var(--border)" stroke-width="${isOdd ? 1 : 0.5}" opacity="${isOdd ? 0.5 : 0.25}"/>${text}`;
  }).join('');
}

/**
 * Render a complete <svg> line chart element.
 *
 * @param {Object}   opts
 * @param {string[]} opts.days           - YYYY-MM-DD, oldest first
 * @param {string}   opts.today          - Today's date string
 * @param {Array}    opts.series         - Each: { label, color,
 *                                           getVal(date,i)→number|null,
 *                                           getLabel(date,v)→string,
 *                                           rNormal?, rToday? }
 * @param {number}   opts.yMin           - Y domain minimum
 * @param {number}   opts.yMax           - Y domain maximum
 * @param {number[]} [opts.yTicks]       - Gridline Y positions
 * @param {Object}   [opts.yTickLabels]  - { [v]: string } named tick labels
 * @param {number}   [opts.vw=800]
 * @param {number}   [opts.vh=80]
 * @param {number}   [opts.pl=28]
 * @param {number}   [opts.pr=8]
 * @param {number}   [opts.pt=10]
 * @param {number}   [opts.pb=22]
 * @param {string}   [opts.svgClass]
 * @param {string}   [opts.ariaLabel]
 * @param {boolean}  [opts.showXLabels=true]
 * @param {boolean}  [opts.showGrid=true]
 * @param {number|null} [opts.midLineY]  - Horizontal baseline at this Y value (sparklines)
 * @returns {string}
 */
export function renderLineChart({
  days, today, series,
  yMin, yMax,
  yTicks,
  yTickLabels,
  vw = 800, vh = 80,
  pl = 28, pr = 8, pt = 10, pb = 22,
  svgClass = 'logbook-mood-chart-svg',
  ariaLabel = 'Chart',
  showXLabels = true,
  showGrid = true,
  midLineY = null,
}) {
  const n = Math.max(days.length - 1, 1);
  const plotH = vh - pt - pb;
  const range = (yMax - yMin) || 1;
  const xPos = i => pl + (i / n) * (vw - pl - pr);
  const yPos = v => pt + (1 - (v - yMin) / range) * plotH;

  const ticks = yTicks ?? Array.from({ length: Math.round(yMax - yMin) + 1 }, (_, k) => yMin + k);
  const grid = showGrid ? _buildYGrid(ticks, yPos, yTickLabels, vw, pl, pr) : '';
  const xLabels = showXLabels ? _buildXLabels(days, xPos, vh) : '';
  const mid = midLineY != null
    ? `<line x1="${pl}" y1="${yPos(midLineY).toFixed(1)}" x2="${vw - pr}" y2="${yPos(midLineY).toFixed(1)}" stroke="var(--border)" stroke-width="0.8" opacity="0.4"/>`
    : '';

  let paths = '', dots = '';
  for (const s of series) {
    const pathD = _buildPath(days, s.getVal, xPos, yPos);
    if (pathD) paths += `<path d="${pathD}" fill="none" stroke="${s.color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
    dots += _buildDots(days, today, s.getVal, s.getLabel, s.label, s.color, xPos, yPos, s.rNormal ?? 3.5, s.rToday ?? 5);
  }

  return `<svg viewBox="0 0 ${vw} ${vh}" width="100%" class="${_esc(svgClass)}" aria-label="${_esc(ariaLabel)}">${mid}${grid}${paths}${dots}${xLabels}</svg>`;
}

/**
 * Render a legend of color-line + label items.
 * @param {Array<{label:string, color:string}>} items
 * @returns {string}
 */
export function renderChartLegend(items) {
  return items
    .map(({ label, color }) =>
      `<span class="lmcl-item"><svg width="16" height="4" style="overflow:visible"><line x1="0" y1="2" x2="16" y2="2" stroke="${color}" stroke-width="2.5" stroke-linecap="round"/></svg>${_esc(label)}</span>`)
    .join('');
}

/**
 * Build the standard 14-day window ending today.
 * @param {()=>string} todayFn
 * @param {(date:string, offset:number)=>string} dateAddFn
 * @returns {{ days: string[], today: string }}
 */
export function build14DayWindow(todayFn, dateAddFn) {
  const t = todayFn();
  const days = [];
  for (let i = 13; i >= 0; i--) days.push(dateAddFn(t, -i));
  return { days, today: t };
}
