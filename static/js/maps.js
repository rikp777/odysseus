/**
 * Shared map helpers.
 *
 * This module stays local-first by default: it renders a simple coordinate
 * plot and builds optional outbound map-search URLs. When the server supplies
 * a tile config, it can also render browser-loaded raster map tiles.
 */

const TILE_SIZE = 256;
const VIRTUAL_MAP_WIDTH = 960;
const VIRTUAL_MAP_HEIGHT = 520;
const WEB_MERCATOR_LAT_LIMIT = 85.05112878;

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

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function tileTemplateUrl(template, zoom, x, y) {
  const subdomains = ['a', 'b', 'c'];
  const subdomain = subdomains[Math.abs(x + y + zoom) % subdomains.length];
  return String(template || '')
    .replace(/\{z\}/g, String(zoom))
    .replace(/\{x\}/g, String(x))
    .replace(/\{y\}/g, String(y))
    .replace(/\{s\}/g, subdomain);
}

function worldPixels(latitude, longitude, zoom) {
  const lat = clamp(Number(latitude), -WEB_MERCATOR_LAT_LIMIT, WEB_MERCATOR_LAT_LIMIT);
  const lon = clamp(Number(longitude), -180, 180);
  const sinLat = Math.sin(lat * Math.PI / 180);
  const scale = TILE_SIZE * (2 ** zoom);
  return {
    x: ((lon + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
  };
}

function chooseZoom(points, latitudeKey, longitudeKey, maxZoom, zoomOffset = 0) {
  const cappedMax = clamp(Math.floor(Number(maxZoom) || 18), 1, 20);
  const offset = clamp(Math.trunc(Number(zoomOffset) || 0), -5, 5);
  if (points.length <= 1) return clamp(Math.min(cappedMax, 16) + offset, 1, cappedMax);
  for (let zoom = cappedMax; zoom >= 1; zoom -= 1) {
    const worlds = points.map(point => worldPixels(point[latitudeKey], point[longitudeKey], zoom));
    const xs = worlds.map(point => point.x);
    const ys = worlds.map(point => point.y);
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);
    if (spanX <= VIRTUAL_MAP_WIDTH * 0.76 && spanY <= VIRTUAL_MAP_HEIGHT * 0.72) {
      return clamp(zoom + offset, 1, cappedMax);
    }
  }
  return clamp(1 + offset, 1, cappedMax);
}

function wrapTileX(x, tileCount) {
  return ((x % tileCount) + tileCount) % tileCount;
}

function renderPin(point, label, left, top, idKey, pinDataAttribute) {
  return `<button type="button" class="geo-map-pin" style="left:${left.toFixed(2)}%;top:${top.toFixed(2)}%;" ${pinDataAttribute}="${esc(point[idKey] || '')}" title="${esc(label)}"><span>${esc(label)}</span></button>`;
}

function renderRasterTileMap(points, {
  idKey,
  labelKey,
  latitudeKey,
  longitudeKey,
  pinDataAttribute,
  tileConfig,
  zoomOffset = 0,
}) {
  const zoom = chooseZoom(points, latitudeKey, longitudeKey, tileConfig?.max_zoom, zoomOffset);
  const worldPoints = points.map(point => ({
    point,
    world: worldPixels(point[latitudeKey], point[longitudeKey], zoom),
  }));
  const xs = worldPoints.map(item => item.world.x);
  const ys = worldPoints.map(item => item.world.y);
  const centerX = (Math.min(...xs) + Math.max(...xs)) / 2;
  const centerY = (Math.min(...ys) + Math.max(...ys)) / 2;
  const topLeftX = centerX - VIRTUAL_MAP_WIDTH / 2;
  const topLeftY = centerY - VIRTUAL_MAP_HEIGHT / 2;
  const tileCount = 2 ** zoom;
  const startX = Math.floor(topLeftX / TILE_SIZE);
  const endX = Math.floor((topLeftX + VIRTUAL_MAP_WIDTH) / TILE_SIZE);
  const startY = Math.floor(topLeftY / TILE_SIZE);
  const endY = Math.floor((topLeftY + VIRTUAL_MAP_HEIGHT) / TILE_SIZE);
  const tiles = [];
  for (let y = startY; y <= endY; y += 1) {
    if (y < 0 || y >= tileCount) continue;
    for (let x = startX; x <= endX; x += 1) {
      const wrappedX = wrapTileX(x, tileCount);
      const left = ((x * TILE_SIZE - topLeftX) / VIRTUAL_MAP_WIDTH) * 100;
      const top = ((y * TILE_SIZE - topLeftY) / VIRTUAL_MAP_HEIGHT) * 100;
      const width = (TILE_SIZE / VIRTUAL_MAP_WIDTH) * 100 + 0.25;
      const height = (TILE_SIZE / VIRTUAL_MAP_HEIGHT) * 100 + 0.25;
      const src = tileTemplateUrl(tileConfig.tile_url, zoom, wrappedX, y);
      tiles.push(`<img class="geo-map-tile" src="${esc(src)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" style="left:${left.toFixed(3)}%;top:${top.toFixed(3)}%;width:${width.toFixed(3)}%;height:${height.toFixed(3)}%;">`);
    }
  }
  const pins = worldPoints.map(({ point, world }) => {
    const label = point[labelKey] || point.display_name || point.name || 'Place';
    const left = clamp(((world.x - topLeftX) / VIRTUAL_MAP_WIDTH) * 100, 2, 98);
    const top = clamp(((world.y - topLeftY) / VIRTUAL_MAP_HEIGHT) * 100, 2, 98);
    return renderPin(point, label, left, top, idKey, pinDataAttribute);
  }).join('');
  const attribution = String(tileConfig?.attribution || '').trim();
  return `
    <div class="geo-map geo-map-tiles" data-map-provider="${esc(tileConfig?.provider || 'tiles')}">
      <div class="geo-map-tile-layer">${tiles.join('')}</div>
      <div class="geo-map-controls" aria-label="Map controls">
        <button type="button" data-map-zoom="in" title="Zoom in" aria-label="Zoom in">+</button>
        <button type="button" data-map-zoom="out" title="Zoom out" aria-label="Zoom out">-</button>
        <button type="button" data-map-zoom="reset" title="Reset zoom" aria-label="Reset zoom">Reset</button>
      </div>
      <div class="geo-map-pin-layer">${pins}</div>
      ${attribution ? `<div class="geo-map-attribution">${esc(attribution)}</div>` : ''}
    </div>
  `;
}

export function renderCoordinateMap(items, {
  idKey = 'id',
  labelKey = 'name',
  latitudeKey = 'latitude',
  longitudeKey = 'longitude',
  pinDataAttribute = 'data-map-point',
  emptyText = 'Add latitude and longitude to pin places here.',
  tileConfig = null,
  zoomOffset = 0,
} = {}) {
  const points = pointsWithCoordinates(items, { latitudeKey, longitudeKey });
  if (points.length && tileConfig?.tiles_enabled && tileConfig?.tile_url) {
    return renderRasterTileMap(points, {
      idKey,
      labelKey,
      latitudeKey,
      longitudeKey,
      pinDataAttribute,
      tileConfig,
      zoomOffset,
    });
  }
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
    return renderPin(point, label, left, top, idKey, pinDataAttribute);
  }).join('');
  return `<div class="geo-map">${pins || `<div class="geo-map-empty">${esc(emptyText)}</div>`}</div>`;
}
