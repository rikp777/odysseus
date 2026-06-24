export const LOGBOOK_TABS = Object.freeze(['write', 'mood', 'data', 'review', 'people', 'places', 'ai']);

export function logbookTabLabel(tab) {
  return tab === 'ai' ? 'Enhance' : String(tab || 'write')[0].toUpperCase() + String(tab || 'write').slice(1);
}

export function normalizeLogbookTab(tab) {
  return LOGBOOK_TABS.includes(tab) ? tab : 'write';
}

export function logbookTabTransition(tab, state = {}) {
  const activeTab = normalizeLogbookTab(tab);
  if (activeTab === 'ai') {
    return {
      action: 'enhance',
      activeTab,
      browseOpen: false,
      writeToolsOpen: false,
      historyOpen: false,
    };
  }
  const keepWriteState = activeTab === 'write';
  return {
    action: 'tab',
    activeTab,
    browseOpen: keepWriteState ? Boolean(state.browseOpen) : false,
    writeToolsOpen: keepWriteState ? Boolean(state.writeToolsOpen) : false,
    historyOpen: keepWriteState ? Boolean(state.historyOpen) : false,
  };
}

export function syncLogbookTabChrome(modal, {
  activeTab = 'write',
  browseOpen = false,
  writeToolsOpen = false,
} = {}) {
  const currentTab = normalizeLogbookTab(activeTab);
  modal?.querySelectorAll?.('[data-logbook-tab]')?.forEach(btn => {
    const active = btn.dataset.logbookTab === currentTab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const body = modal?.querySelector?.('.logbook-body');
  if (body) {
    body.dataset.activeTab = currentTab;
    body.classList.toggle('browse-open', currentTab === 'write' && Boolean(browseOpen));
    body.classList.toggle('write-more-open', currentTab === 'write' && Boolean(writeToolsOpen));
  }
  const browseBtn = modal?.querySelector?.('#logbook-toggle-browse');
  if (browseBtn) {
    const expanded = currentTab === 'write' && Boolean(browseOpen);
    browseBtn.classList.toggle('active', expanded);
    browseBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }
  const moreBtn = modal?.querySelector?.('#logbook-toggle-write-more');
  if (moreBtn) {
    const expanded = currentTab === 'write' && Boolean(writeToolsOpen);
    moreBtn.classList.toggle('active', expanded);
    moreBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }
}
