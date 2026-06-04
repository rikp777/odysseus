export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

export function dateString(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export function today() {
  return dateString(new Date());
}

export function dateAdd(value, days) {
  const d = new Date(`${value}T12:00:00`);
  d.setDate(d.getDate() + days);
  return dateString(d);
}

export function dateLabel(value) {
  const current = today();
  if (value === current) return 'Today';
  if (value === dateAdd(current, -1)) return 'Yesterday';
  if (value === dateAdd(current, 1)) return 'Tomorrow';
  return value;
}

export function cleanKey(value) {
  return String(value || 'datapoint')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'datapoint';
}

