export const LOGBOOK_LINK_RE = /\[([^\]\n]{1,160})\]\((person:[A-Za-z0-9_-]{2,100}|place:[A-Za-z0-9_-]{2,100}|location:[A-Za-z0-9_-]{2,100}|data:[A-Za-z0-9_-]{2,80}|food:[A-Za-z0-9_-]{2,100}|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\)/g;
export const LOGBOOK_PERSON_RE = /(^|[^\w.])@(?:\[([^\]\n]{1,80})\]|"([^"\n]{1,80})"|([A-Za-z0-9À-ÖØ-öø-ÿ][A-Za-z0-9À-ÖØ-öø-ÿ_-]*(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-z0-9À-ÖØ-öø-ÿ0-9_-]*|van|de|der|den|ten|ter|von|da|del|di|la|le|du)){0,3}))/g;
export const LOGBOOK_LOCATION_RE = /(^|[^\w#])#(?:\[([^\]\n]{1,80})\]|"([^"\n]{1,80})"|([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-z0-9À-ÖØ-öø-ÿ_-]*(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-z0-9À-ÖØ-öø-ÿ0-9_-]*|van|de|der|den|ten|ter|von|da|del|di|la|le|du)){0,3}))/g;

export function slugName(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/^(person|place|location|data|food):/i, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function linkKind(target) {
  const value = String(target || '').toLowerCase();
  if (value.startsWith('place:') || value.startsWith('location:')) return 'location';
  if (value.startsWith('data:') || value.startsWith('food:')) return 'data';
  return 'person';
}

export function displayNameFromSlug(value) {
  const particles = new Set(['van', 'de', 'der', 'den', 'ten', 'ter', 'von', 'da', 'del', 'di', 'la', 'le', 'du']);
  return slugName(value)
    .split('_')
    .filter(Boolean)
    .map((part, index) => (index > 0 && particles.has(part)) ? part : part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function personForLink(people = [], target, label = '') {
  const targetSlug = slugName(target);
  const labelSlug = slugName(label);
  return (people || []).find(person => {
    const slugs = [
      person.canonical_name,
      person.display_name,
      ...(person.aliases || []),
    ].map(slugName).filter(Boolean);
    return slugs.includes(targetSlug) || Boolean(labelSlug && slugs.includes(labelSlug));
  }) || null;
}

export function locationForLink(locations = [], target, label = '', { includeHidden = false } = {}) {
  const targetSlug = slugName(target);
  const labelSlug = slugName(label);
  return (locations || []).find(location => {
    if (location.hidden && !includeHidden) return false;
    const slugs = [
      location.canonical_name,
      location.display_name,
      ...(location.aliases || []),
    ].map(slugName).filter(Boolean);
    return slugs.includes(targetSlug) || Boolean(labelSlug && slugs.includes(labelSlug));
  }) || null;
}

export function entityKey(item) {
  return item?.id || slugName(item?.canonical_name || item?.display_name || '');
}

function addEntity(list, item) {
  const key = entityKey(item);
  if (!key || list.some(existing => entityKey(existing) === key)) return;
  list.push(item);
}

export function entityFromLabel(kind, label, target = '', { people = [], locations = [] } = {}) {
  if (kind === 'location') {
    const existing = locationForLink(locations, target, label, { includeHidden: true });
    if (existing?.hidden) return null;
    if (existing) return existing;
  }
  const existing = kind === 'location' ? null : personForLink(people, target, label);
  if (existing) return existing;
  const displayName = label || displayNameFromSlug(target);
  return displayName ? { id: '', display_name: displayName, canonical_name: slugName(target || label) } : null;
}

export function currentEntitiesFromContent(content, { people: knownPeople = [], locations: knownLocations = [] } = {}) {
  const text = String(content || '');
  const people = [];
  const locations = [];
  LOGBOOK_LINK_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_LINK_RE)) {
    const kind = linkKind(match[2]);
    if (kind === 'location') {
      addEntity(locations, entityFromLabel('location', match[1], match[2], { locations: knownLocations }));
    } else if (kind !== 'data') {
      addEntity(people, entityFromLabel('person', match[1], match[2], { people: knownPeople }));
    }
  }
  LOGBOOK_PERSON_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_PERSON_RE)) {
    const label = (match[2] || match[3] || match[4] || '').replace(/\s+/g, ' ').trim();
    if (label) addEntity(people, entityFromLabel('person', label, '', { people: knownPeople }));
  }
  LOGBOOK_LOCATION_RE.lastIndex = 0;
  for (const match of text.matchAll(LOGBOOK_LOCATION_RE)) {
    const label = (match[2] || match[3] || match[4] || '').replace(/\s+/g, ' ').trim();
    if (label) addEntity(locations, entityFromLabel('location', label, '', { locations: knownLocations }));
  }
  return { people, locations };
}

export function entityListSignature(people = [], locations = []) {
  const personKeys = people.map(entityKey).filter(Boolean).sort().join(',');
  const locationKeys = locations.map(entityKey).filter(Boolean).sort().join(',');
  return `${personKeys}|${locationKeys}`;
}

export function selectionLinkParts(text) {
  const value = String(text || '');
  const leading = value.match(/^\s*/)?.[0] || '';
  const trailing = value.match(/\s*$/)?.[0] || '';
  const label = value
    .slice(leading.length, value.length - trailing.length)
    .replace(/[\[\]\r\n]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 160);
  return label ? { leading, label, trailing } : null;
}

export function selectionLinkTarget(kind, label, { people = [], locations = [] } = {}) {
  if (kind === 'food') return 'data:food';
  if (kind === 'location') {
    const location = locationForLink(locations, '', label);
    return `place:${slugName(location?.canonical_name || location?.display_name || label)}`;
  }
  const person = personForLink(people, '', label);
  return `person:${slugName(person?.canonical_name || person?.display_name || label)}`;
}

export function mentionMarkdown(name, people = []) {
  const person = personForLink(people, '', name);
  const target = `person:${slugName(person?.canonical_name || person?.display_name || name)}`;
  return `[${name}](${target})`;
}

export function locationMarkdown(name, locations = []) {
  const location = locationForLink(locations, '', name);
  const target = `place:${slugName(location?.canonical_name || location?.display_name || name)}`;
  return `[${name}](${target})`;
}
