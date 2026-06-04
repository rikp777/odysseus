function formatProviderId(provider) {
  return String(provider || 'Provider')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, function(ch) { return ch.toUpperCase(); })
    .trim() || 'Provider';
}

export function normalizeProviderCatalog(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.map(function(item) {
    var id = String(item && item.id || '').trim();
    if (!id) return null;
    return {
      id: id,
      label: String(item.label || formatProviderId(id)).trim() || formatProviderId(id),
      short_label: String(item.short_label || '').trim(),
      token_hint: String(item.token_hint || '').trim() || 'Provider billing API token',
    };
  }).filter(Boolean);
}

export function providerLabel(catalog, provider) {
  var id = String(provider || '').trim();
  var meta = (catalog || []).find(function(item) { return item.id === id; });
  return meta ? meta.label : formatProviderId(id);
}

export function providerHint(catalog, provider) {
  var id = String(provider || '').trim();
  var meta = (catalog || []).find(function(item) { return item.id === id; });
  return meta ? meta.token_hint : 'Provider billing API token';
}

export function providerOptions(catalog, selected, escapeHtml, extraProviderIds) {
  var seen = new Set();
  var options = [];

  (catalog || []).forEach(function(item) {
    if (!item || !item.id || seen.has(item.id)) return;
    seen.add(item.id);
    options.push({ id: item.id, label: item.label || formatProviderId(item.id) });
  });

  (extraProviderIds || []).forEach(function(provider) {
    var id = String(provider || '').trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    options.push({ id: id, label: formatProviderId(id) });
  });

  return options.map(function(option) {
    return '<option value="' + escapeHtml(option.id) + '"' + (option.id === selected ? ' selected' : '') + '>' +
      escapeHtml(option.label) +
      '</option>';
  }).join('');
}
