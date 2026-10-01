/**
 * Shared primitives: DOM helpers, formatting, toasts, modals, local storage.
 *
 * All user-visible text goes through `t()` so the whole UI follows the active
 * locale.
 */

import { intlLocale, t } from './i18n.js';

// ── DOM ────────────────────────────────────────────────────────────────────

export const $ = (selector, scope = document) => scope.querySelector(selector);
export const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

/**
 * Terse element builder. Supports `tag`, `tag.class`, `tag#id` and
 * `tag#id.class` selectors.
 *   h('div.card', { onclick: fn }, [h('h2', 'Title'), 'text'])
 *   h('div#stats.grid-3', tileNodes)
 */
export function h(tag, props = null, children = null) {
  let selector = String(tag);
  let id = '';
  const idMatch = selector.match(/#([^.#]+)/);
  if (idMatch) {
    id = idMatch[1];
    selector = selector.replace(/#[^.#]+/, '');
  }
  const [name, ...classes] = selector.split('.');
  const el = document.createElement(name || 'div');
  if (id) el.id = id;
  const classList = classes.filter(Boolean);
  if (classList.length) el.className = classList.join(' ');

  if (props && typeof props === 'object' && !Array.isArray(props) && !(props instanceof Node)) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class' || key === 'className') {
        el.className = [el.className, value].filter(Boolean).join(' ');
      } else if (key === 'dataset') {
        Object.assign(el.dataset, value);
      } else if (key === 'style' && typeof value === 'object') {
        Object.assign(el.style, value);
      } else if (key === 'html') {
        el.innerHTML = value;
      } else if (key.startsWith('on') && typeof value === 'function') {
        el.addEventListener(key.slice(2), value);
      } else if (key in el && key !== 'list' && typeof value !== 'object') {
        el[key] = value;
      } else {
        el.setAttribute(key, value === true ? '' : value);
      }
    }
  } else if (props !== null && props !== undefined) {
    children = props;
  }

  append(el, children);
  return el;
}

export function append(parent, children) {
  if (children === null || children === undefined || children === false) return parent;
  if (Array.isArray(children)) {
    for (const child of children) append(parent, child);
    return parent;
  }
  parent.append(children instanceof Node ? children : document.createTextNode(String(children)));
  return parent;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function mount(node, ...children) {
  clear(node);
  append(node, children);
  return node;
}

// ── Strings & numbers ──────────────────────────────────────────────────────

export function formatBytes(bytes, { placeholder = '—', precision = 1 } = {}) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return placeholder;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = n;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index === 0 ? 0 : precision)} ${units[index]}`;
}

export function formatCount(n) {
  const value = Number(n) || 0;
  return value.toLocaleString(intlLocale());
}

export function formatPercent(fraction) {
  const n = Number(fraction);
  if (!Number.isFinite(n)) return '—';
  return `${Math.round(n * 100)}%`;
}

/** Relative time for recent stamps, absolute for older ones. */
export function formatWhen(input) {
  const date = parseDate(input);
  if (!date) return '—';
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 45) return t('time.justNow');
  if (diff < 3600) return t('time.minutesAgo', { n: Math.round(diff / 60) });
  if (diff < 86400) return t('time.hoursAgo', { n: Math.round(diff / 3600) });
  if (diff < 604800) return t('time.daysAgo', { n: Math.round(diff / 86400) });
  return date.toLocaleDateString(intlLocale(), { month: 'short', day: 'numeric' });
}

export function formatDateTime(input) {
  const date = parseDate(input);
  if (!date) return '—';
  return date.toLocaleString(intlLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function parseDate(input) {
  if (!input) return null;
  if (input instanceof Date) return input;
  // The API stores UTC timestamps as "YYYY-MM-DD HH:MM:SS" without a zone.
  const normalised = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(input)
    ? `${input.replace(' ', 'T')}Z`
    : input;
  const date = new Date(normalised);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function basename(path) {
  if (!path) return '';
  return String(path).split(/[/\\]/).pop();
}

export function extname(name) {
  const base = basename(name);
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

export function humanFileKind(name) {
  const ext = extname(name);
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'avif', 'ico', 'heic', 'tiff'].includes(ext)) return 'image';
  if (['mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'wmv', 'm4v', 'ts', 'm3u8', 'mpd'].includes(ext)) return 'video';
  if (['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'opus', 'wma'].includes(ext)) return 'audio';
  if (['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'epub', 'csv', 'txt', 'rtf'].includes(ext)) return 'document';
  if (['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'zst'].includes(ext)) return 'archive';
  if (['woff', 'woff2', 'ttf', 'otf', 'eot'].includes(ext)) return 'font';
  return 'file';
}

export function debounce(fn, wait = 250) {
  let timer = null;
  const wrapped = (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
  wrapped.cancel = () => window.clearTimeout(timer);
  return wrapped;
}

// ── Storage ────────────────────────────────────────────────────────────────

const STORAGE_PREFIX = 'autoget:';

export const store = {
  get(key, fallback = null) {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
    } catch {
      /* private mode / quota — silently ignore */
    }
  },
  remove(key) {
    try { localStorage.removeItem(STORAGE_PREFIX + key); } catch { /* ignore */ }
  },
};

// ── Icons ──────────────────────────────────────────────────────────────────

const ICON_PATHS = {
  dashboard: '<path d="M3 3h8v8H3zM13 3h8v5h-8zM13 12h8v9h-8zM3 15h8v6H3z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  download: '<path d="M12 3v12m0 0l-4-4m4 4l4-4M4 19h16"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  robot: '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4M9 14h.01M15 14h.01M8 20v2M16 20v2"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="M7 4l12 8-12 8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  trash: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  check: '<path d="M4 12l5 5L20 6"/>',
  alert: '<path d="M12 3l9 16H3zM12 9v5M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  file: '<path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z"/><path d="M14 3v4h4"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="M4 17l5-5 4 4 3-3 4 4"/>',
  video: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/>',
  audio: '<path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/>',
  archive: '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>',
  zap: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18z"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6z"/>',
  code: '<path d="M9 18l-6-6 6-6M15 6l6 6-6 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
};

export function icon(name, className = '') {
  const paths = ICON_PATHS[name] || ICON_PATHS.file;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.9');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  if (className) svg.setAttribute('class', className);
  svg.innerHTML = paths;
  return svg;
}

export function kindIcon(name) {
  const kind = humanFileKind(name);
  const map = { image: 'image', video: 'video', audio: 'audio', archive: 'archive', document: 'file' };
  return icon(map[kind] || 'file', 'file-icon');
}

// ── Toasts ─────────────────────────────────────────────────────────────────

const TOAST_ICONS = { success: 'check', error: 'alert', warning: 'alert', info: 'info' };

export function toast(message, { type = 'success', title = '', timeout = 4200 } = {}) {
  const root = $('#toasts');
  if (!root) return () => {};

  const node = h('div.toast', { dataset: { type } }, [
    h('span.toast-icon', icon(TOAST_ICONS[type] || 'info')),
    h('div.toast-body', [
      title ? h('div.toast-title', title) : null,
      h('div.toast-text', message),
    ]),
    h('button.toast-close', {
      type: 'button', 'aria-label': t('modal.dismiss'), onclick: () => dismiss(),
    }, '\u00d7'),
  ]);

  let timer = null;
  const dismiss = () => {
    window.clearTimeout(timer);
    if (!node.isConnected) return;
    node.dataset.leaving = 'true';
    window.setTimeout(() => node.remove(), 200);
  };

  root.append(node);
  if (timeout) timer = window.setTimeout(dismiss, timeout);
  return dismiss;
}

// ── Modal ──────────────────────────────────────────────────────────────────

/**
 * Show a modal. `build(close)` returns the body node; `actions` is an array of
 * `{label, variant, onClick(close)}`.
 */
export function modal({ title, build, actions = [], width = 560, onClose = null }) {
  const root = $('#modal-root');
  if (!root) return { close() {} };

  let closed = false;
  const close = (result) => {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', onKey);
    backdrop.remove();
    onClose?.(result);
  };

  const onKey = (event) => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
  };

  const body = h('div.modal-body');
  append(body, build(close));

  const backdrop = h('div.modal-backdrop', {
    onclick: (event) => { if (event.target === backdrop) close(); },
  }, [
    h('div.modal', { role: 'dialog', 'aria-modal': 'true', style: { width: `${width}px` } }, [
      h('div.modal-head', [
        h('h2', title),
        h('button.icon-btn', {
          type: 'button', 'aria-label': t('action.close'), onclick: () => close(),
        }, icon('close')),
      ]),
      body,
      actions.length
        ? h('div.modal-foot', actions.map((action) => h('button.btn', {
            type: 'button',
            class: action.variant || '',
            onclick: () => action.onClick ? action.onClick(close) : close(),
          }, action.label)))
        : null,
    ]),
  ]);

  root.append(backdrop);
  document.addEventListener('keydown', onKey);
  window.setTimeout(() => $('input, textarea, button', backdrop)?.focus(), 30);
  return { close };
}

export function confirmDialog({ title, message, confirmLabel = null, cancelLabel = null,
                                danger = false }) {
  return new Promise((resolve) => {
    modal({
      title,
      width: 440,
      onClose: (result) => resolve(result === true),
      build: () => h('p', { style: { color: 'var(--text-soft)' } }, message),
      actions: [
        { label: cancelLabel || t('action.cancel'), variant: 'btn-ghost',
          onClick: (close) => close(false) },
        {
          label: confirmLabel || t('action.delete'),
          variant: danger ? 'btn-danger' : 'btn-primary',
          onClick: (close) => close(true),
        },
      ],
    });
  });
}

// ── Copy to clipboard ──────────────────────────────────────────────────────

export async function copyText(text, label = null) {
  try {
    await navigator.clipboard.writeText(text);
    toast(label || t('action.copied'), { type: 'success', timeout: 1600 });
    return true;
  } catch {
    toast(t('error.clipboard'), { type: 'warning' });
    return false;
  }
}

/** A <pre> block with a hover copy button. */
export function codeBlock(text, { language = '' } = {}) {
  const pre = h('pre.code', {}, h('code', { class: language }, text));
  pre.append(h('button.copy-btn', {
    type: 'button',
    onclick: (event) => { event.stopPropagation(); copyText(text); },
  }, t('action.copy')));
  return pre;
}

// ── Small components ───────────────────────────────────────────────────────

/** Status pill. Falls back to the raw value when a status has no translation. */
export function statusBadge(status) {
  const safe = String(status || 'pending').toLowerCase();
  const label = t(`status.${safe}`);
  return h('span', { class: `badge badge-${safe}` }, label === `status.${safe}` ? safe : label);
}

export function progressBar({ value = 0, tone = '', indeterminate = false } = {}) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return h('div.progress', {
    dataset: indeterminate ? { indeterminate: 'true' } : {},
    role: 'progressbar',
    'aria-valuenow': indeterminate ? '' : Math.round(pct),
    'aria-valuemin': '0',
    'aria-valuemax': '100',
  }, h('div.progress-fill', {
    style: { width: indeterminate ? '35%' : `${pct}%` },
    dataset: tone ? { tone } : {},
  }));
}

export function emptyState({ iconName = 'search', title, message, action = null }) {
  return h('div.empty', [
    h('span.empty-icon', icon(iconName)),
    h('h3', title),
    message ? h('p', message) : null,
    action,
  ]);
}

export function skeletonList(rows = 5) {
  return h('div', Array.from({ length: rows }, () =>
    h('div.skeleton-row', [
      h('div.skeleton', { style: { flex: '2' } }),
      h('div.skeleton', { style: { flex: '1' } }),
      h('div.skeleton', { style: { flex: '0 0 80px' } }),
    ])));
}

export function banner({ tone = 'info', title, message, iconName = null }) {
  const icons = { info: 'info', warning: 'alert', danger: 'alert' };
  return h(`div.banner.banner-${tone}`, [
    icon(iconName || icons[tone] || 'info'),
    h('div.banner-body', [
      title ? h('strong', title) : null,
      message ? h('div', { style: { color: 'var(--text-muted)' } }, message) : null,
    ]),
  ]);
}

/** Attach a data-on attribute to a chip/switch wrapper for styling. */
export function bindToggle(input) {
  const wrapper = input.closest('.chip, .switch');
  if (!wrapper) return;
  const sync = () => { wrapper.dataset.on = String(input.checked); };
  input.addEventListener('change', sync);
  sync();
}

/** A stat tile with a tinted icon chip — the dashboard's building block. */
export function statTile({ label, value, foot = '', iconName = 'chart',
                           color = 'var(--accent)', soft = 'var(--accent-soft)' }) {
  return h('div.stat', { style: { '--stat-color': color, '--stat-soft': soft } }, [
    h('span.stat-icon', icon(iconName)),
    h('div.stat-body', [
      h('div.stat-label', label),
      h('div.stat-value', String(value)),
      foot ? h('div.stat-foot', foot) : null,
    ]),
  ]);
}

export function kvRow(key, value) {
  return h('div.kv-item', [h('div.kv-key', key), h('div.kv-val', value)]);
}
