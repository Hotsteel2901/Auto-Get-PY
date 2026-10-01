/**
 * Application bootstrap.
 *
 * Registers the pages, wires the sidebar, the theme and language switches and
 * the keyboard shortcuts, starts the live progress channel, and keeps the
 * header in sync with the server.
 */

import { $, store, toast } from './core.js';
import { api } from './api.js';
import {
  applyStatic, availableLocales, getLocale, onLocaleChange, setLocale, t,
} from './i18n.js';
import {
  buildNav, currentPageId, currentPage, init as initRouter, navigate,
  register as registerPage, relabelNav, rerender,
} from './router.js';
import { connect as connectWs, onStateChange, reconnectNow } from './ws.js';
import { startLiveSync } from './live.js';

import { dashboardPage } from './pages/dashboard.js';
import { newTaskPage } from './pages/new-task.js';
import { downloadsPage, focusDownloadsSearch } from './pages/downloads.js';
import { filesPage, focusFilesSearch } from './pages/files.js';
import { settingsPage } from './pages/settings.js';
import { agentsPage } from './pages/agents.js';

const PAGES = [
  dashboardPage,
  newTaskPage,
  downloadsPage,
  filesPage,
  agentsPage,
  settingsPage,
];

const THEME_KEY = 'theme';

function bootstrap() {
  for (const page of PAGES) registerPage(page);

  applyTheme(store.get(THEME_KEY, 'light'));
  applyStatic();

  initRouter({
    main: $('#main'),
    onNavigate: (page) => {
      $('#page-title').textContent = t(page.titleKey);
      $('#page-subtitle').textContent = page.subtitleKey ? t(page.subtitleKey) : '';
      syncNav();
      closeMobileNav();
    },
  });

  buildNav($('#nav'), { onSelect: closeMobileNav });
  syncNav();

  wireSidebar();
  wireShortcuts();
  wireScrollShadows();

  onLocaleChange(handleLocaleChange);

  startLiveSync();
  onStateChange(renderConnection);
  connectWs();

  refreshVersion();
  window.setInterval(refreshVersion, 60_000);
}

// ── Locale & theme ─────────────────────────────────────────────────────────

async function handleLocaleChange(locale) {
  applyStatic();
  relabelNav($('#nav'));
  await rerender();
  // The header is set by onNavigate during rerender, but guard against a page
  // that failed to mount leaving the old title behind.
  const page = currentPage();
  if (page) {
    $('#page-title').textContent = t(page.titleKey);
    $('#page-subtitle').textContent = page.subtitleKey ? t(page.subtitleKey) : '';
  }
  updateLangButton(locale);
  toast(t('lang.switched'), { type: 'info', timeout: 1800 });
}

function updateLangButton(locale) {
  const button = $('#lang-toggle');
  if (!button) return;
  const entry = availableLocales().find((item) => item.id === locale);
  // Show the *other* language as the action hint.
  const next = availableLocales().find((item) => item.id !== locale);
  button.textContent = next ? next.short : (entry?.short || 'EN');
  button.title = t('lang.toggle');
  button.setAttribute('aria-label', t('lang.toggle'));
}

function applyTheme(theme) {
  const next = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  store.set(THEME_KEY, next);

  const button = $('#theme-toggle');
  if (button) {
    // Show a sun in dark mode (the action) and a moon in light mode.
    button.replaceChildren(
      iconFor(next === 'dark' ? 'sun' : 'moon'));
    button.title = t('theme.toggle');
    button.setAttribute('aria-label', t('theme.toggle'));
  }
  return next;
}

function iconFor(name) {
  const namespace = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(namespace, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = name === 'sun'
    ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
    : '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>';
  return svg;
}

// ── Chrome ─────────────────────────────────────────────────────────────────

function syncNav() {
  const id = currentPageId();
  for (const item of document.querySelectorAll('.nav-item')) {
    if (item.dataset.page === id) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  }
}

function wireSidebar() {
  $('#menu-toggle')?.addEventListener('click', () => {
    const open = document.body.dataset.nav === 'open';
    document.body.dataset.nav = open ? 'closed' : 'open';
    const scrim = $('#scrim');
    if (scrim) scrim.hidden = open;
  });
  $('#scrim')?.addEventListener('click', closeMobileNav);

  $('#theme-toggle')?.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    toast(t(next === 'dark' ? 'theme.switched.toDark' : 'theme.switched.toLight'),
      { timeout: 1500 });
  });

  $('#lang-toggle')?.addEventListener('click', () => {
    const next = getLocale() === 'zh' ? 'en' : 'zh';
    setLocale(next);
  });

  updateLangButton(getLocale());

  $('#conn-status')?.addEventListener('click', () => reconnectNow());
}

function closeMobileNav() {
  document.body.dataset.nav = 'closed';
  const scrim = $('#scrim');
  if (scrim) scrim.hidden = true;
}

function renderConnection(state) {
  const node = $('#conn-status');
  if (!node) return;
  const labels = {
    open: t('conn.live'),
    connecting: t('conn.connecting'),
    reconnecting: t('conn.reconnecting'),
    closed: t('conn.offline'),
    idle: t('conn.idle'),
  };
  node.dataset.state = state;
  const text = $('.conn-text', node);
  if (text) text.textContent = labels[state] || state;
  node.title = state === 'open' ? t('conn.title.live') : t('conn.title.reconnect');
}

async function refreshVersion() {
  const label = $('#version-label');
  try {
    const info = await api.system();
    if (label) label.textContent = `v${info.version}`;
    document.body.dataset.authRequired = String(Boolean(info.auth_required));
  } catch {
    if (label) label.textContent = '—';
  }
}

function wireScrollShadows() {
  const topbar = $('.topbar');
  const onScroll = () => {
    if (topbar) topbar.dataset.stuck = String(window.scrollY > 4);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────

const GO_TO = {
  d: 'dashboard',
  n: 'new-task',
  l: 'downloads',
  f: 'files',
  a: 'agents',
  s: 'settings',
};

function wireShortcuts() {
  let pendingGo = false;
  let pendingTimer = null;

  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const typing = target instanceof HTMLElement
      && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
          || target.isContentEditable);

    if (event.key === 'Escape') {
      closeMobileNav();
      if (typing) target.blur();
      return;
    }

    if (event.metaKey || event.ctrlKey || event.altKey) return;

    if (event.key === '/') {
      event.preventDefault();
      focusCurrentSearch();
      return;
    }

    if (typing) return;

    if (event.key === 'g') {
      pendingGo = true;
      window.clearTimeout(pendingTimer);
      pendingTimer = window.setTimeout(() => { pendingGo = false; }, 1200);
      return;
    }

    if (pendingGo && GO_TO[event.key]) {
      event.preventDefault();
      pendingGo = false;
      window.clearTimeout(pendingTimer);
      navigate(GO_TO[event.key]);
      return;
    }

    if (event.key === 'n') {
      event.preventDefault();
      navigate('new-task');
    }
  });
}

function focusCurrentSearch() {
  switch (currentPageId()) {
    case 'downloads': focusDownloadsSearch(); break;
    case 'files': focusFilesSearch(); break;
    case 'new-task': document.getElementById('f-url')?.focus(); break;
    default: break;
  }
}

// ── Boot ───────────────────────────────────────────────────────────────────

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap);
} else {
  bootstrap();
}
