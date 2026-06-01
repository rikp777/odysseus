// Model Picker — chatbox model selector dropdown
// Extracted from sessions.js

import { providerLogo } from './providers.js';
import uiModule from './ui.js';
import settingsModule from './settings.js';
import { sortModelObjects } from './modelSort.js';

const API_BASE = window.location.origin;

// ── Shared keyboard nav for model pickers ──
function _handlePickerKeydown(e, listEl, itemSelector, closeFn) {
  if (e.key === 'Escape') { closeFn(); return; }
  if (e.key === 'Enter') {
    e.preventDefault();
    const active = listEl.querySelector(itemSelector + '.kb-active') || listEl.querySelector(itemSelector);
    if (active) active.click();
    return;
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const items = [...listEl.querySelectorAll(itemSelector)].filter(el => el.style.display !== 'none');
    if (!items.length) return;
    const cur = items.findIndex(el => el.classList.contains('kb-active'));
    items.forEach(el => el.classList.remove('kb-active'));
    let next;
    if (e.key === 'ArrowDown') next = cur < items.length - 1 ? cur + 1 : 0;
    else next = cur > 0 ? cur - 1 : items.length - 1;
    items[next].classList.add('kb-active');
    items[next].scrollIntoView({ block: 'nearest' });
  }
}

// Dependencies injected via initModelPicker()
let _deps = null;
let _autoSelectingDefault = false;

function _costDisplayEnabled() {
  return window.__odysseusBillingDisplayEnabled !== false;
}

function _modelExists(modelId, url) {
  if (!modelId || !window.modelsModule || !window.modelsModule.getCachedItems) return false;
  const items = window.modelsModule.getCachedItems() || [];
  if (!items.length) return true;
  const targetUrl = (url || '').replace(/\/+$/, '');
  return items.some(item => {
    if (item.offline) return false;
    const itemUrl = (item.url || '').replace(/\/+$/, '');
    const models = (item.models || []).concat(item.models_extra || []);
    return models.includes(modelId) && (!targetUrl || itemUrl === targetUrl);
  });
}

function _formatUsd(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  if (n < 0.01) return `$${n.toFixed(3)}`;
  if (n < 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(2).replace(/\.00$/, '')}`;
}

function _shortUnit(unit) {
  const value = String(unit || '').toLowerCase();
  if (value.includes('character')) return '1M chars';
  if (value.includes('video')) return '1M video tok';
  if (value.includes('image')) return '1M image tok';
  if (value.includes('reranking')) return '1M rank tok';
  if (value.includes('token')) return '1M tok';
  return unit || 'unit';
}

function _formatModelPrice(pricing) {
  if (!pricing) return null;
  const input = pricing.input_usd_per_unit;
  const output = pricing.output_usd_per_unit;
  const unit = pricing.unit || '1M tokens';
  if (input != null && output != null) {
    const compact = `${_formatUsd(input)}/${_formatUsd(output)} · ${_shortUnit(unit)}`;
    const button = `${_formatUsd(input)}/${_formatUsd(output)}`;
    const detail = `Input ${_formatUsd(input)} / output ${_formatUsd(output)} per ${unit}`;
    return { compact, button, detail };
  }
  if (input != null) {
    const compact = `${_formatUsd(input)} in · ${_shortUnit(unit)}`;
    const button = `${_formatUsd(input)} in`;
    const detail = `Input ${_formatUsd(input)} per ${unit}`;
    return { compact, button, detail };
  }
  if (pricing.price_usd_per_unit != null) {
    const compact = `${_formatUsd(pricing.price_usd_per_unit)} · ${_shortUnit(unit)}`;
    const button = _formatUsd(pricing.price_usd_per_unit);
    const detail = `${_formatUsd(pricing.price_usd_per_unit)} per ${unit}`;
    return { compact, button, detail };
  }
  return null;
}

function _getModelPricing(modelId, url, endpointId) {
  if (!modelId || !window.modelsModule || !window.modelsModule.getCachedItems) return null;
  const items = window.modelsModule.getCachedItems() || [];
  const targetUrl = (url || '').replace(/\/+$/, '');
  const targetEndpointId = endpointId ? String(endpointId) : '';
  let looseMatch = null;
  for (const item of items) {
    const pricing = item.model_pricing || {};
    if (!pricing[modelId]) continue;
    const itemUrl = (item.url || '').replace(/\/+$/, '');
    const sameEndpoint = targetEndpointId && String(item.endpoint_id || '') === targetEndpointId;
    const sameUrl = targetUrl && itemUrl === targetUrl;
    if (sameEndpoint || sameUrl) return pricing[modelId];
    if (!looseMatch) looseMatch = pricing[modelId];
  }
  return looseMatch;
}

/**
 * Initialize the model picker dropdown.
 * @param {Object} deps
 * @param {function} deps.getCurrentSessionId - returns current session ID
 * @param {function} deps.getSessions - returns sessions array
 * @param {function} deps.getPendingChat - returns _pendingChat object
 * @param {function} deps.setPendingChat - sets _pendingChat object
 * @param {function} deps.createDirectChat - creates a new direct chat session
 */
export function initModelPicker(deps) {
  _deps = deps;
  _initModelPickerDropdown();
}

function _initModelPickerDropdown() {
  const wrap = document.getElementById('model-picker-wrap');
  const btn = document.getElementById('model-picker-btn');
  const menu = document.getElementById('model-picker-menu');
  const search = document.getElementById('model-picker-search');
  const listEl = document.getElementById('model-picker-list');
  const searchRow = menu ? menu.querySelector('.model-picker-search-row') : null;
  if (!wrap || !btn || !menu || !search || !listEl) return;

  function _close() {
    if (menu.classList.contains('hidden')) return;
    // Restore scroll button
    const _scrollBtn = document.getElementById('scroll-bottom-btn');
    if (_scrollBtn) _scrollBtn.style.display = '';
    menu.classList.add('closing');
    menu.addEventListener('animationend', function _onDone() {
      menu.removeEventListener('animationend', _onDone);
      menu.classList.remove('closing');
      menu.classList.add('hidden');
      search.value = '';
    }, { once: true });
    // Fallback if animationend doesn't fire
    setTimeout(() => {
      if (!menu.classList.contains('hidden')) {
        menu.classList.remove('closing');
        menu.classList.add('hidden');
        search.value = '';
      }
    }, 200);
  }

  function _openPickerShortcut(kind) {
    _close();
    try {
      if (kind === 'cookbook') {
        if (window.cookbookModule && typeof window.cookbookModule.open === 'function') {
          window.cookbookModule.open();
        } else {
          const btn = document.getElementById('tool-cookbook-btn') || document.getElementById('rail-cookbook');
          if (btn) btn.click();
          else location.hash = '#cookbook';
        }
      } else if (kind === 'settings') {
        if (settingsModule && typeof settingsModule.open === 'function') settingsModule.open();
      } else if (window.adminModule && typeof window.adminModule.open === 'function') {
        window.adminModule.open('services');
      } else if (settingsModule && typeof settingsModule.open === 'function') {
        settingsModule.open('services');
      }
    } catch (_) {}
  }

  // Local endpoint health — only probed for LOCAL endpoints, since
  // cloud APIs are essentially always up. Cached briefly on the
  // server side too (8s TTL). Picker opens trigger a refresh.
  let _localProbe = {};            // {endpoint_id: {alive, latency_ms, error}}
  let _localProbeFetchedAt = 0;
  const _LOCAL_PROBE_TTL_MS = 5000;

  async function _refreshLocalProbe() {
    const now = Date.now();
    if (now - _localProbeFetchedAt < _LOCAL_PROBE_TTL_MS) return;
    _localProbeFetchedAt = now;
    try {
      const r = await fetch('/api/model-endpoints/probe-local', { credentials: 'same-origin' });
      if (r.ok) _localProbe = (await r.json()) || {};
    } catch (_) { /* leave stale data; picker still works */ }
  }

  function _getAllModels() {
    const items = (window.modelsModule && window.modelsModule.getCachedItems) ? window.modelsModule.getCachedItems() : [];
    const result = [];
    const seen = new Set();
    items.forEach(item => {
      if (item.offline) return;
      const allModels = (item.models || []).concat(item.models_extra || []);
      const allDisplay = (item.models_display || []).concat(item.models_extra_display || []);
      const modelPricing = item.model_pricing || {};
      // Mark local endpoints whose live probe failed.
      const probeResult = item.endpoint_id ? _localProbe[item.endpoint_id] : null;
      const isLocalDead = !!(probeResult && probeResult.alive === false);
      allModels.forEach((mid, i) => {
        // Deduplicate by model ID — prefer DB endpoints over env-discovered
        if (seen.has(mid)) return;
        seen.add(mid);
        result.push({
          mid,
          display: (allDisplay[i] || mid).split('/').pop(),
          url: item.url,
          endpointId: item.endpoint_id,
          epName: item.endpoint_name || '',
          pricing: modelPricing[mid] || null,
          stale: isLocalDead,
          staleReason: isLocalDead ? (probeResult.error || 'not responding') : '',
        });
      });
    });
    return sortModelObjects(result);
  }

  function _populate(filter) {
    listEl.innerHTML = '';
    const all = _getAllModels();
    const q = (filter || '').toLowerCase();
    const hasAnyModel = all.length > 0;
    listEl.classList.toggle('is-empty', !hasAnyModel);
    menu.classList.toggle('no-models', !hasAnyModel);
    if (search) {
      search.placeholder = hasAnyModel ? 'Search models…' : 'No models connected';
    }
    if (searchRow) {
      searchRow.classList.toggle('searching', !!filter);
    }

    // Load favorites
    const favs = (function() { try { return JSON.parse(localStorage.getItem('odysseus-model-favorites') || '[]'); } catch { return []; } })();

    // Partition: favorites first, then rest
    const favModels = [];
    const restModels = [];
    all.forEach(m => {
      if (q && !m.mid.toLowerCase().includes(q) && !m.display.toLowerCase().includes(q)) return;
      if (favs.includes(m.mid)) favModels.push(m);
      else restModels.push(m);
    });
    sortModelObjects(favModels).forEach(function(m, i) { favModels[i] = m; });
    sortModelObjects(restModels).forEach(function(m, i) { restModels[i] = m; });

    function _addSection(label) {
      const el = document.createElement('div');
      el.className = 'mp-section-label';
      el.textContent = label;
      listEl.appendChild(el);
    }
    function _addRow(m) {
      const row = document.createElement('div');
      row.className = 'model-switch-item';
      if (m.stale) {
        row.classList.add('model-switch-stale');
        row.style.opacity = '0.45';
        row.title = `Local server appears offline: ${m.staleReason}. Click to try anyway, or relaunch in Cookbook.`;
      }
      const _mlogo = providerLogo(m.mid);
      if (_mlogo) {
        const logoSpan = document.createElement('span');
        logoSpan.className = 'provider-logo';
        logoSpan.style.opacity = '0.6';
        logoSpan.innerHTML = _mlogo;
        row.appendChild(logoSpan);
      }
      const nameSpan = document.createElement('span');
      nameSpan.className = 'model-switch-name';
      nameSpan.textContent = m.display;
      row.appendChild(nameSpan);
      if (m.stale) {
        const badge = document.createElement('span');
        badge.className = 'model-switch-stale-badge';
        badge.textContent = 'offline';
        badge.style.cssText = 'font-size:10px;opacity:0.7;padding:1px 6px;border:1px solid var(--border);border-radius:8px;margin-left:6px;';
        row.appendChild(badge);
      }
      const metaSpan = document.createElement('span');
      metaSpan.className = 'model-switch-meta';
      const priceInfo = _formatModelPrice(m.pricing);
      if (priceInfo) {
        const priceSpan = document.createElement('span');
        priceSpan.className = 'model-switch-price';
        priceSpan.textContent = priceInfo.compact;
        priceSpan.title = priceInfo.detail + (m.pricing.note ? ` (${m.pricing.note})` : '');
        metaSpan.appendChild(priceSpan);
      }
      const epSpan = document.createElement('span');
      epSpan.className = 'model-switch-ep';
      // Don't show endpoint name if it matches the model name (local self-hosted)
      const _epDisplay = m.epName && !m.display.toLowerCase().includes(m.epName.toLowerCase().split('/').pop()) ? m.epName : '';
      epSpan.textContent = _epDisplay;
      if (_epDisplay) metaSpan.appendChild(epSpan);
      if (metaSpan.children.length) row.appendChild(metaSpan);
      row.addEventListener('click', () => _pick(m));
      listEl.appendChild(row);
    }

    if (favModels.length > 0) {
      _addSection('Favorites');
      favModels.forEach(_addRow);
    }
    if (restModels.length > 0) {
      if (favModels.length > 0) _addSection('All models');
      restModels.forEach(_addRow);
    }
    if (listEl.children.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'model-switch-empty';
      if (hasAnyModel) {
        empty.textContent = 'No matching models';
      } else {
        return;
      }
      listEl.appendChild(empty);
    }
  }

  async function _pick(m) {
    const currentSessionId = _deps.getCurrentSessionId();
    const _pendingChat = _deps.getPendingChat();

    // Broadcast immediately so listeners (e.g. the tour) can advance without
    // waiting for the async session-create/PATCH that follows.
    try { document.dispatchEvent(new CustomEvent('odysseus:model-picked', { detail: m })); } catch {}

    // Blur search input before closing to dismiss keyboard on mobile
    if (document.activeElement) document.activeElement.blur();
    _close();
    // Refocus main textarea — skip on mobile to avoid keyboard bounce
    if (window.innerWidth >= 768) {
      const _ta = document.getElementById('message');
      if (_ta) setTimeout(() => _ta.focus(), 50);
    }
    if (!currentSessionId && _pendingChat) {
      // Already have a deferred session — just update the model
      _deps.setPendingChat({ url: m.url, modelId: m.mid, endpointId: m.endpointId });
      // Header stays as session name — model switch only updates picker
      updateModelPicker();
      uiModule.showToast(`Using ${m.display}`);
      return;
    } else if (!currentSessionId) {
      // No session yet — create one with this model
      await _deps.createDirectChat(m.url, m.mid, m.endpointId);
    } else {
      // Existing session with no model — PATCH it
      const fd = new FormData();
      fd.append('model', m.mid);
      fd.append('endpoint_url', m.url);
      if (m.endpointId) fd.append('endpoint_id', m.endpointId);
      try {
        const res = await fetch(`${API_BASE}/api/session/${currentSessionId}`, { method: 'PATCH', body: fd });
        if (!res.ok) {
          uiModule.showError('Failed to set model');
          return;
        }
        const sessions = _deps.getSessions();
        const s = sessions.find(x => x.id === currentSessionId);
        if (s) { s.model = m.mid; s.endpoint_url = m.url; s.endpoint_id = m.endpointId || ''; }
        // Header stays as session name — model info shown in picker only
      } catch (e) {
        uiModule.showError('Failed to set model: ' + e);
        return;
      }
    }
    // Update picker visibility — model is now set
    updateModelPicker();
    uiModule.showToast(`Using ${m.display}`);
  }

  document.addEventListener('odysseus:auto-select-model', async (e) => {
    const detail = (e && e.detail) || {};
    const currentSessionId = _deps.getCurrentSessionId();
    const sessions = _deps.getSessions();
    const current = sessions.find(x => x.id === currentSessionId);
    const pending = _deps.getPendingChat();
    if ((current && current.model) || (pending && pending.modelId)) return;

    if (window.modelsModule && window.modelsModule.refreshModels) {
      try { await window.modelsModule.refreshModels(true); } catch (_) {}
    }
    const items = window.modelsModule && window.modelsModule.getCachedItems ? window.modelsModule.getCachedItems() : [];
    const targetEndpointId = detail.endpointId ? String(detail.endpointId) : '';
    const targetModel = detail.modelId || '';
    let match = null;
    for (const item of items) {
      if (item.offline) continue;
      if (targetEndpointId && String(item.endpoint_id || '') !== targetEndpointId) continue;
      const models = (item.models || []).concat(item.models_extra || []);
      const displays = (item.models_display || []).concat(item.models_extra_display || []);
      const idx = targetModel ? models.indexOf(targetModel) : (models.length ? 0 : -1);
      if (idx >= 0) {
        match = {
          mid: models[idx],
          display: (displays[idx] || models[idx]).split('/').pop(),
          url: item.url || detail.url || '',
          endpointId: item.endpoint_id || detail.endpointId || '',
          epName: item.endpoint_name || detail.endpointName || '',
          pricing: (item.model_pricing || {})[models[idx]] || null,
        };
        break;
      }
    }
    if (!match && detail.modelId && detail.url) {
      match = {
        mid: detail.modelId,
        display: String(detail.modelId).split('/').pop(),
        url: detail.url,
        endpointId: detail.endpointId || '',
        epName: detail.endpointName || '',
      };
    }
    if (match) await _pick(match);
  });

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.classList.contains('hidden') || menu.classList.contains('closing')) {
      // Force-clear any in-progress close animation
      menu.classList.remove('closing', 'hidden');
      _populate('');
      if (window.modelsModule && window.modelsModule.refreshModels) {
        window.modelsModule.refreshModels(true).then(() => {
          if (!menu.classList.contains('hidden')) _populate(search.value || '');
          updateModelPicker();
        }).catch(() => {});
      }
      // Kick off a local-endpoint probe — when it returns, re-render
      // the list so stale local servers get dimmed. Cloud entries
      // aren't probed; they stay visible.
      _refreshLocalProbe().then(() => {
        if (!menu.classList.contains('hidden')) _populate(search.value || '');
      });
      if (window.innerWidth >= 768) search.focus();
      // Hide scroll button so it doesn't overlap
      const _scrollBtn = document.getElementById('scroll-bottom-btn');
      if (_scrollBtn) _scrollBtn.style.display = 'none';
    } else {
      _close();
    }
  });

  search.addEventListener('input', () => _populate(search.value));
  search.addEventListener('click', (e) => e.stopPropagation());
  search.addEventListener('keydown', (e) => {
    _handlePickerKeydown(e, listEl, '.model-switch-item', _close);
  });
  const addModelsBtn = document.getElementById('model-picker-add-models-btn');
  if (addModelsBtn) {
    addModelsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _openPickerShortcut('models');
    });
  }
  document.addEventListener('click', (e) => {
    if (!menu.classList.contains('hidden') && !menu.contains(e.target) && e.target !== btn) {
      _close();
    }
  });
}

/**
 * Update the model picker label to show the current model.
 * Always visible — shows current model name or "Select model" if none.
 * Called after selectSession, createDirectChat, and model switch.
 */
export function updateModelPicker() {
  if (!_deps) return;
  const label = document.getElementById('model-picker-label');
  const btn = document.getElementById('model-picker-btn');
  if (!label) return;
  // Hide model picker when group chat is active
  const wrap = document.getElementById('model-picker-wrap');
  if (window.groupModule && window.groupModule.isActive()) {
    if (wrap) { wrap.style.display = 'none'; }
    return;
  }
  // Reset inline visibility (may have been hidden by typing in previous session)
  if (wrap) {
    wrap.style.display = '';
    wrap.style.opacity = '';
    wrap.style.pointerEvents = '';
  }
  const currentSessionId = _deps.getCurrentSessionId();
  const sessions = _deps.getSessions();
  const _pendingChat = _deps.getPendingChat();
  const s = sessions.find(x => x.id === currentSessionId);
  let modelId = null;
  let modelUrl = '';
  let modelEndpointId = '';
  if (s && s.model) {
    modelId = s.model;
    modelUrl = s.endpoint_url || '';
    modelEndpointId = s.endpoint_id || s.endpointId || '';
    if (!_modelExists(modelId, modelUrl)) {
      modelId = null;
      modelUrl = '';
      modelEndpointId = '';
    }
  } else if (_pendingChat && _pendingChat.modelId) {
    modelId = _pendingChat.modelId;
    modelUrl = _pendingChat.url || '';
    modelEndpointId = _pendingChat.endpointId || '';
    if (!_modelExists(modelId, modelUrl)) {
      _deps.setPendingChat(null);
      modelId = null;
      modelUrl = '';
      modelEndpointId = '';
    }
  }
  // SECURITY: deliberately NOT auto-injecting `odysseus-model-favorites[0]`
  // here. localStorage favorites are per-browser, not per-user, so on a
  // shared browser the previous account's first favorited model would
  // silently pre-populate the chatbox of the next user that signed in. If
  // we have no session model and no pending-chat pick, fall through to
  // the "Select model" placeholder below.

  // Check if selected model is still available — fall back ONLY for pending chats with no user selection
  // Never override an existing session's model — the user explicitly chose it
  if (modelId && !currentSessionId && _pendingChat && window.modelsModule && window.modelsModule.getCachedItems) {
    const items = window.modelsModule.getCachedItems();
    const allAvailable = [];
    items.forEach(item => {
      if (item.offline) return;
      (item.models || []).concat(item.models_extra || []).forEach(m => allAvailable.push(m));
    });
    if (allAvailable.length > 0 && !allAvailable.includes(modelId)) {
      // Model no longer available — switch to first available
      const fallback = items.find(item => !item.offline && (item.models || []).length > 0);
      if (fallback) {
        modelId = fallback.models[0];
        modelUrl = fallback.url || '';
        modelEndpointId = fallback.endpoint_id || '';
        _deps.setPendingChat({ url: modelUrl, modelId, endpointId: modelEndpointId });
      }
    }
  }
  if (!modelId && !_autoSelectingDefault && window.modelsModule && window.modelsModule.getCachedItems) {
    const items = window.modelsModule.getCachedItems();
    const first = items.find(item => !item.offline && ((item.models || []).length || (item.models_extra || []).length));
    if (first) {
      const models = (first.models || []).concat(first.models_extra || []);
      modelId = models[0];
      modelUrl = first.url || '';
      modelEndpointId = first.endpoint_id || '';
      if (!currentSessionId) {
        _deps.setPendingChat({ url: modelUrl, modelId, endpointId: modelEndpointId });
      } else {
        if (s) { s.model = modelId; s.endpoint_url = modelUrl; s.endpoint_id = modelEndpointId; }
        _autoSelectingDefault = true;
        const fd = new FormData();
        fd.append('model', modelId);
        fd.append('endpoint_url', modelUrl);
        if (modelEndpointId) fd.append('endpoint_id', modelEndpointId);
        fetch(`${API_BASE}/api/session/${currentSessionId}`, { method: 'PATCH', body: fd })
          .catch(() => {})
          .finally(() => { _autoSelectingDefault = false; });
      }
    }
  }

  const displayName = modelId ? modelId.split('/').pop() : 'Select model';
  const logo = modelId ? providerLogo(modelId) : null;
  const pricing = modelId ? _getModelPricing(modelId, modelUrl, modelEndpointId) : null;
  const priceInfo = _formatModelPrice(pricing);
  label.replaceChildren();
  if (logo) {
    const logoSpan = document.createElement('span');
    logoSpan.className = 'model-picker-logo';
    logoSpan.innerHTML = logo;
    label.appendChild(logoSpan);
  }
  const nameSpan = document.createElement('span');
  nameSpan.className = 'model-picker-name';
  nameSpan.textContent = displayName;
  label.appendChild(nameSpan);
  if (priceInfo && _costDisplayEnabled()) {
    const priceSpan = document.createElement('span');
    priceSpan.className = 'model-picker-cost-current';
    priceSpan.textContent = priceInfo.button || priceInfo.compact;
    priceSpan.title = priceInfo.detail + (pricing.note ? ` (${pricing.note})` : '');
    label.appendChild(priceSpan);
  }
  if (btn) {
    const titleBits = [modelId ? `Switch model: ${modelId}` : 'Switch model'];
    if (priceInfo && _costDisplayEnabled()) titleBits.push(priceInfo.detail);
    if (pricing && pricing.source && _costDisplayEnabled()) titleBits.push(pricing.source);
    btn.title = titleBits.join(' · ');
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('odysseus-billing-visibility-changed', () => {
    try { updateModelPicker(); } catch (_) {}
  });
}
