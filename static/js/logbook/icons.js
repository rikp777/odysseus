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
  return lineIcon('<path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/>', size);
}
