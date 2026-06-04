/**
 * Shared map helpers.
 *
 * This module stays local-first: it renders a simple coordinate plot and
 * builds optional outbound map-search URLs, but it does not load map tiles,
 * geocode addresses, or call third-party APIs.
 */

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function hasCoordinate(value) {
  return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
}

export function mapSearchUrl(query, { provider = 'openstreetmap' } = {}) {
  const text = String(query || '').trim();
  if (!text) return '';
  const encoded = encodeURIComponent(text);
  if (provider === 'apple') return `https://maps.apple.com/?q=${encoded}`;
  if (provider === 'google') return `https://www.google.com/maps/search/?api=1&query=${encoded}`;
  return `https://www.openstreetmap.org/search?query=${encoded}`;
}

export function pointsWithCoordinates(items, {
  latitudeKey = 'latitude',
  longitudeKey = 'longitude',
} = {}) {
  return (items || []).filter(item => hasCoordinate(item?.[latitudeKey]) && hasCoordinate(item?.[longitudeKey]));
}

export function pointsWithoutCoordinates(items, {
  latitudeKey = 'latitude',
  longitudeKey = 'longitude',
} = {}) {
  return (items || []).filter(item => !hasCoordinate(item?.[latitudeKey]) || !hasCoordinate(item?.[longitudeKey]));
}

export function renderCoordinateMap(items, {
  idKey = 'id',
  labelKey = 'name',
  latitudeKey = 'latitude',
  longitudeKey = 'longitude',
  pinDataAttribute = 'data-map-point',
  emptyText = 'Add latitude and longitude to pin places here.',
} = {}) {
  const points = pointsWithCoordinates(items, { latitudeKey, longitudeKey });
  const lats = points.map(point => Number(point[latitudeKey]));
  const lons = points.map(point => Number(point[longitudeKey]));
  const minLat = Math.min(...lats, 0);
  const maxLat = Math.max(...lats, 1);
  const minLon = Math.min(...lons, 0);
  const maxLon = Math.max(...lons, 1);
  const latRange = maxLat - minLat || 1;
  const lonRange = maxLon - minLon || 1;
  const pins = points.map(point => {
    const label = point[labelKey] || point.display_name || point.name || 'Place';
    const left = 6 + ((Number(point[longitudeKey]) - minLon) / lonRange) * 88;
    const top = 94 - ((Number(point[latitudeKey]) - minLat) / latRange) * 88;
    return `<button type="button" class="geo-map-pin" style="left:${left.toFixed(2)}%;top:${top.toFixed(2)}%;" ${pinDataAttribute}="${esc(point[idKey] || '')}" title="${esc(label)}"><span>${esc(label)}</span></button>`;
  }).join('');
  return `<div class="geo-map">${pins || `<div class="geo-map-empty">${esc(emptyText)}</div>`}</div>`;
}
