(() => {
  'use strict';
  const root = document.getElementById('tkbNotificationCenter');
  if (!root) return;
  const bell = root.querySelector('[data-notification-bell]');
  const panel = root.querySelector('[data-notification-panel]');
  const count = root.querySelector('[data-notification-count]');
  const list = root.querySelector('[data-notification-list]');
  const markAll = root.querySelector('[data-notification-mark-all]');
  const projectId = root.dataset.projectId;
  const suffix = projectId ? '?project_id=' + encodeURIComponent(projectId) : '';
  const expanded = new Set();
  const detailsCache = new Map();
  let loading = false;
  let disposed = false;
  let lastId = null;

  const messages = {
    empty: 'Ch\u01b0a c\u00f3 th\u00f4ng b\u00e1o n\u00e0o.',
    error: 'Kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c th\u00f4ng b\u00e1o.',
    loading: '\u0110ang t\u1ea3i chi ti\u1ebft...',
    updated: 'Th\u1eddi kh\u00f3a bi\u1ec3u v\u1eeba \u0111\u01b0\u1ee3c c\u1eadp nh\u1eadt',
    old: 'Th\u00f4ng b\u00e1o n\u00e0y \u0111\u01b0\u1ee3c t\u1ea1o tr\u01b0\u1edbc khi b\u1eadt l\u01b0u chi ti\u1ebft.',
    view: 'Xem chi ti\u1ebft',
    hide: '\u1ea8n chi ti\u1ebft',
    open: 'M\u1edf th\u1eddi kh\u00f3a bi\u1ec3u',
    more: 'thay \u0111\u1ed5i kh\u00e1c kh\u00f4ng \u0111\u01b0\u1ee3c l\u01b0u chi ti\u1ebft (gi\u1edbi h\u1ea1n 100 m\u1ee5c).',
    from: 'T\u1eeb', to: '\u0110\u1ebfn', teacher: 'GV',
    fixed: '\u0110\u00e3 c\u1ed1 \u0111\u1ecbnh', unfixed: '\u0110\u00e3 b\u1ecf c\u1ed1 \u0111\u1ecbnh'
  };

  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function announce(value) {
    const toast = el('div', 'tkb-notification-toast', value);
    toast.setAttribute('role', 'status');
    document.body.append(toast);
    setTimeout(() => toast.remove(), 5000);
  }
  function lessonInfo(item) {
    return [item.class_name, item.subject_name, messages.teacher + ': ' + item.teacher_name].filter(Boolean).join(' \u00b7 ');
  }
  function positionInfo(item) {
    const prior = item.from_slot;
    const next = item.to_slot;
    if (item.action === 'added') return next || '';
    if (item.action === 'removed') return prior || '';
    if (item.action === 'locked') {
      if (item.locked_before !== item.locked_after) {
        return (item.locked_after ? messages.fixed : messages.unfixed) + (next ? ' \u00b7 ' + next : '');
      }
      return next || prior || '';
    }
    if (prior && next && prior !== next) return messages.from + ': ' + prior + ' \u2192 ' + messages.to + ': ' + next;
    return next || prior || '';
  }
  function changeCard(detail) {
    const entry = el('div', 'tkb-notification-change');
    entry.append(el('b', 'tkb-notification-change-type tkb-notification-change-' + detail.action, detail.action_label));
    entry.append(el('span', 'tkb-notification-change-subject', lessonInfo(detail)));
    const positions = positionInfo(detail);
    if (positions) entry.append(el('span', 'tkb-notification-change-position', positions));
    if (detail.from_assignment) {
      const before = detail.from_assignment;
      entry.append(el('span', 'tkb-notification-change-from', messages.from + ': ' + [before.class_name, before.subject_name, messages.teacher + ': ' + before.teacher_name].filter(Boolean).join(' \u00b7 ')));
    }
    return entry;
  }
  function renderDetailContents(target, state) {
    target.replaceChildren();
    if (state.loading) {
      target.append(el('div', 'tkb-notification-details-state', messages.loading));
      return;
    }
    if (state.error) {
      target.append(el('div', 'tkb-notification-details-state', messages.error));
      return;
    }
    const data = state.data;
    if (!data || !data.details || !data.details.length) {
      target.append(el('div', 'tkb-notification-details-state', messages.old));
      return;
    }
    for (const detail of data.details) target.append(changeCard(detail));
    const missing = Number(data.total_count || 0) - Number(data.stored_count || 0);
    if (missing > 0) target.append(el('p', 'tkb-notification-details-state', '+' + missing + ' ' + messages.more));
  }
  async function markRead(id) {
    const response = await fetch('/api/notifications/' + id + '/read', {
      method: 'POST', credentials: 'same-origin', keepalive: true
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
  }
  async function loadDetails(id, container, item) {
    const state = { loading: true, data: null, error: false };
    detailsCache.set(id, state);
    renderDetailContents(container, state);
    try {
      const response = await fetch('/api/notifications/' + id + '/details', {
        credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      state.data = await response.json();
      state.loading = false;
      if (!item.is_read) {
        try { await markRead(id); item.is_read = true; } catch (_) { /* keep details visible */ }
      }
    } catch (_) {
      state.loading = false;
      state.error = true;
    }
    if (expanded.has(id)) {
      const current = list.querySelector('[data-details-for="' + id + '"]');
      if (current) renderDetailContents(current, state);
    }
    if (item.is_read) refresh();
  }

  function render(items, unread) {
    const scroll = list.scrollTop;
    list.replaceChildren();
    count.hidden = !unread;
    count.textContent = unread > 99 ? '99+' : String(unread);
    if (!items.length) {
      list.append(el('p', 'tkb-notification-empty', messages.empty));
      return;
    }
    for (const item of items) {
      const id = Number(item.id);
      const wrapper = el('article', 'tkb-notification-item' + (item.is_read ? '' : ' is-unread'));
      wrapper.append(el('strong', 'tkb-notification-project', item.project_name));
      wrapper.append(el('span', 'tkb-notification-title', item.title));
      wrapper.append(el('span', 'tkb-notification-summary', item.message));
      if (item.preview) {
        const preview = el('div', 'tkb-notification-preview');
        preview.append(changeCard(item.preview));
        wrapper.append(preview);
      }
      const time = el('time', '', new Date(item.created_at).toLocaleString('vi-VN'));
      time.dateTime = item.created_at;
      wrapper.append(time);
      const actions = el('div', 'tkb-notification-actions');
      const isExpanded = expanded.has(id);
      const toggle = el('button', 'tkb-notification-detail-btn', isExpanded ? messages.hide : messages.view);
      toggle.type = 'button';
      toggle.setAttribute('aria-expanded', String(isExpanded));
      toggle.addEventListener('click', event => {
        // Keep this click inside the notification popup. Rebuilding the whole
        // list here used to detach the clicked button before it bubbled to
        // document, which the outside-click handler mistook for a click away.
        event.stopPropagation();
        const nowExpanded = !expanded.has(id);
        if (nowExpanded) expanded.add(id); else expanded.delete(id);
        toggle.textContent = nowExpanded ? messages.hide : messages.view;
        toggle.setAttribute('aria-expanded', String(nowExpanded));

        const existing = wrapper.querySelector('[data-details-for="' + id + '"]');
        if (!nowExpanded) {
          if (existing) existing.remove();
          return;
        }

        const holder = existing || el('div', 'tkb-notification-details');
        holder.setAttribute('data-details-for', String(id));
        if (!existing) wrapper.append(holder);
        const cached = detailsCache.get(id);
        renderDetailContents(holder, cached || { loading: true });
        if (!cached || cached.error) loadDetails(id, holder, item);
      });
      const link = el('a', 'tkb-notification-open', messages.open + ' \u2197');
      link.href = item.url;
      link.addEventListener('click', () => {
        if (!item.is_read) markRead(id).catch(() => { });
      });
      actions.append(toggle, link);
      wrapper.append(actions);
      if (isExpanded) {
        const detailHolder = el('div', 'tkb-notification-details');
        detailHolder.setAttribute('data-details-for', String(id));
        const state = detailsCache.get(id) || { loading: true };
        renderDetailContents(detailHolder, state);
        wrapper.append(detailHolder);
      }
      list.append(wrapper);
    }
    list.scrollTop = scroll;
  }

  async function refresh() {
    if (loading || disposed || document.hidden) return;
    loading = true;
    try {
      const response = await fetch('/api/notifications' + suffix, {
        credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const result = await response.json();
      const newest = result.items.length ? Number(result.items[0].id) : 0;
      if (lastId !== null && newest > lastId) announce(messages.updated);
      lastId = Math.max(lastId || 0, newest);
      render(result.items, Number(result.unread_count || 0));
    } catch (_) {
      if (lastId === null) list.replaceChildren(el('p', 'tkb-notification-empty', messages.error));
    } finally {
      loading = false;
    }
  }
  bell.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    bell.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) refresh();
  });
  document.addEventListener('click', event => {
    // composedPath retains the original propagation path even if some DOM
    // nodes have been replaced by another click handler during this event.
    const path = typeof event.composedPath === 'function' ? event.composedPath() : null;
    const clickedInside = path ? path.includes(root) : root.contains(event.target);
    if (!clickedInside) {
      panel.hidden = true;
      bell.setAttribute('aria-expanded', 'false');
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      panel.hidden = true;
      bell.setAttribute('aria-expanded', 'false');
    }
  });
  markAll.addEventListener('click', async () => {
    markAll.disabled = true;
    try {
      const response = await fetch('/api/notifications/read-all' + suffix, {
        method: 'POST', credentials: 'same-origin'
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      await refresh();
    } catch (_) { announce(messages.error); }
    finally { markAll.disabled = false; }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  const timer = setInterval(refresh, 12000);
  window.addEventListener('pagehide', () => { disposed = true; clearInterval(timer); }, { once: true });
  refresh();
})();
