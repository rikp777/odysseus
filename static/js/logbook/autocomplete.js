export function entityAutocompleteContext(value, position) {
  const pos = Math.max(0, Number(position) || 0);
  const before = String(value || '').slice(0, pos);
  const match = before.match(/(^|[\s(])([@#])([A-Za-z0-9_-]{0,40})$/);
  if (!match) return null;
  return {
    kind: match[2] === '#' ? 'location' : 'person',
    start: pos - match[3].length - 1,
    end: pos,
    query: match[3].toLowerCase(),
  };
}

export function entityAutocompleteMatches(items = [], query = '', { limit = 8, includeHidden = false } = {}) {
  const term = String(query || '').toLowerCase();
  return (items || [])
    .filter(item => {
      if (item?.hidden && !includeHidden) return false;
      const names = [item?.display_name, ...(item?.aliases || [])]
        .map(value => String(value || '').toLowerCase())
        .filter(Boolean);
      return !term || names.some(name => name.startsWith(term) || name.includes(term));
    })
    .slice(0, limit);
}
