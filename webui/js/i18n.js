/**
 * Internationalisation.
 *
 * `t()` resolves a dotted key against the active locale, falls back to English,
 * then to the key itself so a missing translation is visible rather than blank.
 * Pages subscribe with `onLocaleChange()` and re-render, which keeps the whole
 * UI consistent without every component knowing about translations.
 */

import { DICT, LOCALES } from './locales.js';

const STORAGE_KEY = 'locale';
const DEFAULT_LOCALE = 'zh';
const FALLBACK_LOCALE = 'en';

const listeners = new Set();
let current = resolveInitialLocale();

function resolveInitialLocale() {
  const supported = new Set(LOCALES.map((entry) => entry.id));

  // 1. An explicit `?lang=xx` in the URL wins — handy for sharing a link.
  try {
    const fromQuery = new URLSearchParams(location.search).get('lang');
    if (fromQuery && supported.has(fromQuery.toLowerCase())) {
      return fromQuery.toLowerCase();
    }
  } catch {
    /* no URL context (tests) — fall through */
  }

  // 2. Then whatever the user picked last time.
  try {
    const saved = localStorage.getItem(`autoget:${STORAGE_KEY}`);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (supported.has(parsed)) return parsed;
    }
  } catch {
    /* private mode — fall through */
  }

  // 3. Otherwise the project's primary language. The switch is one click away,
  //    and `?lang=en` overrides this for anyone who prefers English.
  return DEFAULT_LOCALE;
}

export function getLocale() {
  return current;
}

export function availableLocales() {
  return LOCALES;
}

export function setLocale(locale) {
  if (!LOCALES.some((entry) => entry.id === locale) || locale === current) {
    if (locale === current) return;
    return;
  }
  current = locale;
  try {
    localStorage.setItem(`autoget:${STORAGE_KEY}`, JSON.stringify(locale));
  } catch {
    /* ignore */
  }
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
  for (const listener of [...listeners]) {
    try {
      listener(locale);
    } catch (error) {
      console.error('locale listener failed', error);
    }
  }
}

export function onLocaleChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Translate a key.
 *
 *   t('dashboard.recent')
 *   t('downloads.summary', { count: 12, done: 10, size: '4 MB' })
 *
 * Plural forms: define `key_one` and `key_other` and pass `{ n }`.
 */
export function t(key, params = null) {
  const table = DICT[current] || {};
  const fallback = DICT[FALLBACK_LOCALE] || {};

  let template = pick(table, key, params);
  if (template === undefined) template = pick(fallback, key, params);
  if (template === undefined) template = key;

  if (!params) return template;
  return String(template).replace(/\{(\w+)\}/g, (match, name) =>
    (params[name] === undefined || params[name] === null ? match : String(params[name])));
}

function pick(table, key, params) {
  if (params && typeof params.n === 'number') {
    const suffix = params.n === 1 ? '_one' : '_other';
    if (table[key + suffix] !== undefined) return table[key + suffix];
  }
  return table[key];
}

/** Translate a pluralised count: `count(3, 'unit.file')` → "3 files". */
export function count(n, unitKey, extra = null) {
  const noun = t(unitKey);
  const plural = /[^\x00-\x7F]/.test(noun) ? noun : (n === 1 ? noun : `${noun}s`);
  const number = extra ? extra : n.toLocaleString(current === 'zh' ? 'zh-CN' : 'en-US');
  return `${number} ${plural}`;
}

// ── Static markup ───────────────────────────────────────────────────────────

/**
 * Apply translations to declarative attributes:
 *   data-i18n="key"                → textContent
 *   data-i18n-placeholder="key"    → placeholder
 *   data-i18n-title="key"          → title
 *   data-i18n-aria-label="key"     → aria-label
 */
export function applyStatic(root = document) {
  for (const node of root.querySelectorAll('[data-i18n]')) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of root.querySelectorAll('[data-i18n-placeholder]')) {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  }
  for (const node of root.querySelectorAll('[data-i18n-title]')) {
    node.title = t(node.dataset.i18nTitle);
  }
  for (const node of root.querySelectorAll('[data-i18n-aria-label]')) {
    node.setAttribute('aria-label', t(node.dataset.i18nAriaLabel));
  }
  document.documentElement.lang = current === 'zh' ? 'zh-CN' : 'en';
}

/** Locale-aware number/date formatting helpers. */
export function intlLocale() {
  return current === 'zh' ? 'zh-CN' : 'en-US';
}
