function lineIcon(paths, size = 14) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

export function iconBook(size = 16) {
  return lineIcon('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h6M9 11h6M9 15h4"/>', size);
}

export function logbookIcon(kind, size = 14) {
  if (kind === 'location') {
    return lineIcon('<path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/>', size);
  }
  if (kind === 'food') {
    return lineIcon('<path d="M4 3v8"/><path d="M8 3v8"/><path d="M4 7h4"/><path d="M6 11v10"/><path d="M17 3v18"/><path d="M14 3h6"/>', size);
  }
  if (kind === 'unlink') {
    return lineIcon('<path d="m18.84 12.25 1.42-1.42a4 4 0 0 0-5.66-5.66l-2 2"/><path d="m5.16 11.75-1.42 1.42a4 4 0 0 0 5.66 5.66l2-2"/><path d="M8 12h8"/><path d="m4 4 16 16"/>', size);
  }
  if (kind === 'bold') {
    return lineIcon('<path d="M6 4h8a4 4 0 0 1 0 8H6z"/><path d="M6 12h9a4 4 0 0 1 0 8H6z"/>', size);
  }
  if (kind === 'italic') {
    return lineIcon('<path d="M19 4h-9"/><path d="M14 20H5"/><path d="M15 4 9 20"/>', size);
  }
  if (kind === 'link') {
    return lineIcon('<path d="M10 13a5 5 0 0 0 7.54.54l2-2a5 5 0 0 0-7.07-7.07l-1.14 1.14"/><path d="M14 11a5 5 0 0 0-7.54-.54l-2 2a5 5 0 0 0 7.07 7.07l1.14-1.14"/>', size);
  }
  if (kind === 'strike') {
    return lineIcon('<path d="M16 4H9a3 3 0 0 0-2.83 4"/><path d="M14 20H7"/><path d="M4 12h16"/><path d="M10 12c4 0 6 1 6 4a4 4 0 0 1-4 4"/>', size);
  }
  if (kind === 'quote') {
    return lineIcon('<path d="M3 21c3 0 7-1 7-8V5H3v8h4c0 3-1 5-4 6z"/><path d="M14 21c3 0 7-1 7-8V5h-7v8h4c0 3-1 5-4 6z"/>', size);
  }
  if (kind === 'list') {
    return lineIcon('<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>', size);
  }
  if (kind === 'orderedList') {
    return lineIcon('<path d="M10 6h11"/><path d="M10 12h11"/><path d="M10 18h11"/><path d="M4 6h1v4"/><path d="M4 10h2"/><path d="M4 14h2l-2 4h2"/>', size);
  }
  if (kind === 'code') {
    return lineIcon('<path d="m8 9-4 3 4 3"/><path d="m16 9 4 3-4 3"/>', size);
  }
  if (kind === 'codeBlock') {
    return lineIcon('<path d="M4 5h16v14H4z"/><path d="m9 10-2 2 2 2"/><path d="m15 10 2 2-2 2"/>', size);
  }
  if (kind === 'hr') {
    return lineIcon('<path d="M5 12h14"/>', size);
  }
  return lineIcon('<path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/>', size);
}
