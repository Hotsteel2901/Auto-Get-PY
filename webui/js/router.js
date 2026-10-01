/**
 * Hash router with page lifecycle.
 *
 * Each page module exports `{ id, titleKey, subtitleKey, icon,
 * mount(container, ctx), unmount? }`. `mount` may return a cleanup function;
 * the router calls it before mounting the next page, which is what keeps
 * timers and WebSocket subscriptions from piling up.
 *
 * Titles are translation keys, so `rerender()` after a language change is
 * enough to update the header, the nav and the page body together.
 */

import { $, $$, append, mount as mountNode } from './core.js';
import { t } from './i18n.js';

const pages = new Map();
const cleanups = [];
let current = null;
let container = null;
let onChange = () => {};

export function register(page) {
  pages.set(page.id, page);
}

export function init({ main, onNavigate }) {
  container = main;
  onChange = onNavigate || (() => {});
  window.addEventListener('hashchange', () => render());
  render();
}

export function currentPageId() {
  return current?.id || null;
}

export function currentPage() {
  return current;
}

export function navigate(id, { replace = false } = {}) {
  const hash = `#${id}`;
  if (location.hash === hash) {
    render();
    return;
  }
  if (replace) {
    history.replaceState(null, '', hash);
    render();
  } else {
    location.hash = hash;
  }
}

function requestedId() {
  const raw = location.hash.replace(/^#\/?/, '').trim();
  return raw || 'dashboard';
}

export async function render() {
  const id = requestedId();
  const page = pages.get(id) || pages.get('dashboard');
  if (!page || !container) return;

  // Tear down the previous page completely.
  while (cleanups.length) {
    const fn = cleanups.pop();
    try { fn(); } catch (error) { console.error('page cleanup failed', error); }
  }

  current = page;
  document.title = `${t(page.titleKey)} · ${t('app.name')}`;
  onChange(page);
  renderToolbar(page);

  const scrollY = window.scrollY;
  const output = document.createElement('div');
  output.className = 'page';
  mountNode(container, output);

  try {
    const cleanup = await page.mount(output, { navigate });
    if (typeof cleanup === 'function') cleanups.push(cleanup);
  } catch (error) {
    console.error(`page "${page.id}" failed to mount`, error);
    mountNode(container, output);
    output.append(
      Object.assign(document.createElement('div'), {
        className: 'card',
        textContent: `This page failed to load: ${error.message}`,
      }),
    );
  }

  // Reset scroll only when switching pages, not on a same-page refresh.
  if (scrollY > 0) window.scrollTo({ top: 0, behavior: 'auto' });
}

/** Re-mount the current page. Used after a locale or theme change. */
export async function rerender() {
  if (!container) return;
  const previous = current;
  current = null;
  await render();
  if (previous) current = pages.get(requestedId()) || current;
}

/**
 * Let a page contribute buttons to the always-visible top bar.
 *
 * Pages that need a primary action (a sticky "start" button above a long form,
 * an export button…) define `toolbar()` returning a node. Keeping it in the
 * header avoids a floating bar that would cover the content underneath.
 */
function renderToolbar(page) {
  const host = document.getElementById('topbar-actions');
  if (!host) return;
  mountNode(host);
  if (typeof page.toolbar !== 'function') return;
  try {
    const node = page.toolbar({ navigate });
    if (node) append(host, node);
  } catch (error) {
    console.error(`page "${page.id}" toolbar failed`, error);
  }
}

export function buildNav(navEl, { onSelect } = {}) {
  mountNode(navEl, [...pages.values()].map((page) => makeNavItem(page, onSelect)));

  const sync = () => {
    const id = currentPageId();
    $$('.nav-item', navEl).forEach((item) => {
      if (item.dataset.page === id) item.setAttribute('aria-current', 'page');
      else item.removeAttribute('aria-current');
    });
  };
  sync();
  return sync;
}

function makeNavItem(page, onSelect) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'nav-item';
  button.dataset.page = page.id;
  button.innerHTML = page.icon || '';
  button.append(document.createTextNode(t(page.titleKey)));
  const badge = document.createElement('span');
  badge.className = 'nav-count';
  badge.dataset.role = 'nav-count';
  badge.hidden = true;
  button.append(badge);
  button.addEventListener('click', () => {
    navigate(page.id);
    onSelect?.(page.id);
  });
  return button;
}

/** Refresh nav labels in place (used after a language change). */
export function relabelNav(navEl) {
  for (const item of navEl.querySelectorAll('.nav-item')) {
    const page = pages.get(item.dataset.page);
    if (!page) continue;
    const label = [...item.childNodes].find((node) => node.nodeType === Node.TEXT_NODE);
    if (label) label.textContent = t(page.titleKey);
    else item.append(document.createTextNode(t(page.titleKey)));
  }
}

/** Update the small counter shown next to a nav entry. */
export function setNavCount(pageId, value) {
  const badge = $(`.nav-item[data-page="${pageId}"] .nav-count`);
  if (!badge) return;
  const count = Number(value) || 0;
  badge.hidden = count === 0;
  badge.textContent = count > 99 ? '99+' : String(count);
}
