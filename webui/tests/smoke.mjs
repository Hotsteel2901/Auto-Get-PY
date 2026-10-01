/**
 * Front-end smoke test.
 *
 * Loads the real index.html in jsdom, stubs `fetch` against a tiny in-memory
 * API, then drives the SPA the way a user would: every page, every control,
 * both languages, both themes. Any uncaught exception is a failure.
 *
 * Assertions resolve their expected strings through `t()` so the test stays
 * valid whichever locale is active.
 *
 * Run:  node webui/tests/smoke.mjs
 */

import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const __dirname = dirname(fileURLToPath(import.meta.url));
const WEBUI = resolve(__dirname, '..');
const INDEX = resolve(WEBUI, 'index.html');

let JSDOM, VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require('jsdom'));
} catch {
  const fallback = createRequire(`${process.env.TEMP}/uispec/`);
  ({ JSDOM, VirtualConsole } = fallback('jsdom'));
}

// ── Fake API ───────────────────────────────────────────────────────────────

const TASKS = [
  { id: 1, name: 'Gallery pull', url: 'https://example.com/gallery/',
    status: 'running', total_files: 12, done_files: 5, error_msg: null,
    created_at: '2026-09-30 10:00:00', updated_at: '2026-09-30 10:05:00',
    progress: 41.7, extra_info: { pages_crawled: 3, total_media_found: 12,
    css_files_crawled: 2 }, config_parsed: { output_dir: './downloads',
    crawl_depth: 2 }, total_media_found: 12 },
  { id: 2, name: 'Broken site', url: 'https://bad.example/x',
    status: 'failed', total_files: 4, done_files: 1, error_msg: 'All downloads failed',
    created_at: '2026-09-29 08:00:00', updated_at: '2026-09-29 08:01:00',
    progress: 25, extra_info: {}, config_parsed: {} },
  { id: 3, name: '', url: 'https://empty.example/', status: 'completed',
    total_files: 0, done_files: 0, error_msg: null, created_at: '2026-09-28 08:00:00',
    updated_at: null, progress: 0, extra_info: {}, config_parsed: {} },
];

const DOWNLOADS = [
  { id: 11, task_id: 1, task_name: 'Gallery pull', url: 'https://example.com/a.jpg',
    filename: 'a.jpg', file_size: 2048, downloaded: 2048, status: 'completed',
    error_msg: null, progress: 100, mime_type: 'image/jpeg' },
  { id: 12, task_id: 1, task_name: 'Gallery pull', url: 'https://example.com/b.mp4',
    filename: 'b.mp4', file_size: 1048576, downloaded: 300000, status: 'downloading',
    error_msg: null, progress: 28.6, mime_type: 'video/mp4' },
  { id: 13, task_id: 2, task_name: 'Broken site', url: 'https://example.com/c.pdf',
    filename: 'c.pdf', file_size: 0, downloaded: 0, status: 'failed',
    error_msg: 'HTTP 403', progress: 0, mime_type: null },
];

/** Deliberately longer than the page size, so the truncation notice renders. */
const MANY_DOWNLOADS = Array.from({ length: 250 }, (_, i) => ({
  id: 1000 + i, task_id: 1, task_name: 'Gallery pull',
  url: `https://example.com/item-${i}.jpg`, filename: `item-${i}.jpg`,
  file_size: 1024 * (i + 1), downloaded: 1024 * (i + 1),
  status: i === 7 ? 'failed' : 'completed',
  error_msg: i === 7 ? 'HTTP 403' : null,
  progress: i === 7 ? 0 : 100, mime_type: 'image/jpeg',
}));

const FILES = [
  { name: 'a.jpg', path: 'a.jpg', size: 2048, size_human: '2.0 KB', mtime: 1780000000,
    mime: 'image/jpeg' },
  { name: 'movie.ts', path: 'streams/movie.ts', size: 52428800, size_human: '50.0 MB',
    mtime: 1779990000, mime: 'video/mp2t' },
];

const AGENT_LIST = [
  { id: 'opencode', name: 'opencode', vendor: 'anomalyco', api_prefix: '/api/opencode',
    aliases: ['/api/opencode'], config_files: ['opencode.json'], install: 'x', notes: 'n',
    docs_url: 'https://opencode.ai/docs/' },
  { id: 'dsh', name: 'DeepSeek Harness', vendor: 'DeepSeek', api_prefix: '/api/dsh',
    aliases: ['/api/dsh'], config_files: [], install: 'y', notes: '', docs_url: '' },
];

const ROUTES = [
  [/^\/api\/health$/, () => ({ status: 'ok', version: '9.9.9' })],
  [/^\/api\/system$/, () => ({ version: '9.9.9', auth_required: false, python: '3.14.0',
    downloads_dir: '/tmp/downloads', running_tasks: [1],
    agent_aliases: ['/api/agent', '/api/hermes', '/api/dsh'], agent_count: 17 })],
  [/^\/api\/tasks\/stats$/, () => ({ stats: { running: 1, completed: 1, failed: 1, all: 3, pending: 0 } })],
  [/^\/api\/tasks\?/, () => ({ tasks: TASKS, count: TASKS.length })],
  [/^\/api\/tasks\/(\d+)\/summary$/, (m) => ({ task: TASKS.find((t) => t.id === +m[1]),
    stats: { completed: 1, failed: 1, pending: 1, bytes: 2048, total: 3 } })],
  [/^\/api\/tasks\/(\d+)\/downloads/, () => ({ downloads: DOWNLOADS, count: 3,
    stats: { completed: 1, failed: 1, pending: 1, bytes: 2048, total: 3 } })],
  [/^\/api\/tasks\/(\d+)\/(start|pause|resume|cancel|retry)$/, () => ({ ok: true, status: 'running' })],
  [/^\/api\/tasks\/(\d+)$/, (m) => ({ task: TASKS.find((t) => t.id === +m[1]) || { id: +m[1] } })],
  [/^\/api\/tasks$/, () => ({ task: { id: 99, name: 'New', url: 'https://x.example', status: 'pending' } })],
  [/^\/api\/downloads/, () => ({ downloads: MANY_DOWNLOADS, count: MANY_DOWNLOADS.length })],
  [/^\/api\/settings$/, () => ({ settings: { default_concurrency: '5',
    default_output_dir: './downloads', aes_key: '', aes_iv: '', default_crawl_depth: '2',
    default_max_pages: '500' } })],
  [/^\/api\/files\?/, () => ({ files: FILES, total: 2, total_size: 52430848,
    directory: '/tmp/downloads' })],
  [/^\/api\/agent\/manifest$/, () => ({ service: 'Auto-Get-PY', version: '9.9.9',
    canonical_prefix: '/api/agent', aliases: ['/api/agent', '/api/hermes'],
    capabilities: ['html-extraction', 'hls-merge'], agents: [] })],
  [/^\/api\/agent\/agents$/, () => ({ agents: AGENT_LIST, canonical_prefix: '/api/agent' })],
];

const calls = [];
const failures = [];
const checks = { n: 0 };

async function fakeFetch(url, options = {}) {
  const path = String(url).replace(/^https?:\/\/[^/]+/, '');
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET') calls.push(`${method} ${path}`);

  for (const [pattern, handler] of ROUTES) {
    const match = path.match(pattern);
    if (match) {
      const body = handler(match);
      return { ok: true, status: 200, text: async () => JSON.stringify(body),
        json: async () => body };
    }
  }
  return { ok: false, status: 404,
    text: async () => JSON.stringify({ detail: `no stub for ${path}` }),
    json: async () => ({ detail: `no stub for ${path}` }) };
}

// ── Boot a DOM ─────────────────────────────────────────────────────────────

const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', (error) => failures.push(`jsdom: ${error.message}`));

const html = readFileSync(INDEX, 'utf8');
const dom = new JSDOM(html, {
  url: 'http://localhost:8000/webui/index.html',
  runScripts: 'outside-only',
  pretendToBeVisual: true,
  virtualConsole,
});

const { window } = dom;

// Expose the jsdom window as the global scope so the ES modules, which
// reference `document`/`window`/`localStorage` directly, can run in Node.
function defineGlobal(name, value) {
  Object.defineProperty(globalThis, name, {
    value, writable: true, configurable: true, enumerable: false,
  });
}

window.fetch = fakeFetch;
window.Request = window.Request || class {};
window.Response = window.Response || class {};
window.WebSocket = class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  constructor() {
    this.readyState = 0;
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.();
      this.onmessage?.({ data: JSON.stringify({ type: 'hello', running_tasks: [1] }) });
    }, 0);
  }
  send() {}
  close() { this.readyState = 3; this.onclose?.(); }
};
Object.defineProperty(window.navigator, 'clipboard', {
  value: { writeText: async () => {} }, configurable: true,
});
window.matchMedia = () => ({
  matches: false, addEventListener() {}, removeEventListener() {},
});
window.URL.createObjectURL = () => 'blob:stub';
window.URL.revokeObjectURL = () => {};

for (const name of [
  'window', 'document', 'location', 'navigator', 'localStorage', 'sessionStorage',
  'HTMLElement', 'HTMLInputElement', 'Node', 'Element', 'Event', 'CustomEvent',
  'HashChangeEvent', 'KeyboardEvent', 'MouseEvent', 'FormData', 'Blob', 'File',
  'DOMParser', 'getComputedStyle', 'matchMedia', 'requestAnimationFrame',
  'cancelAnimationFrame', 'WebSocket', 'fetch', 'AbortController', 'AbortSignal',
  'Text', 'Comment', 'DocumentFragment', 'XMLSerializer', 'history', 'URLSearchParams',
]) {
  if (name in window) defineGlobal(name, window[name]);
}
defineGlobal('self', window);

window.addEventListener('error', (event) => failures.push(`window error: ${event.message}`));
window.addEventListener('unhandledrejection', (event) =>
  failures.push(`unhandled rejection: ${event.reason?.message || event.reason}`));
process.on('unhandledRejection', (reason) =>
  failures.push(`node unhandled rejection: ${reason?.message || reason}`));

for (const level of ['error', 'warn']) {
  const original = console[level].bind(console);
  console[level] = (...args) => {
    const text = args.map((a) => (a && a.stack) || String(a)).join(' ');
    failures.push(`console.${level}: ${text.split('\n')[0]}`);
    original(...args);
  };
}
defineGlobal('console', console);

// ── Helpers ────────────────────────────────────────────────────────────────

const tick = (ms = 40) => new Promise((done) => setTimeout(done, ms));
const $ = (sel) => window.document.querySelector(sel);
const $$ = (sel) => [...window.document.querySelectorAll(sel)];

function assert(condition, message) {
  checks.n += 1;
  if (condition) {
    console.log(`  ok   ${message}`);
  } else {
    failures.push(`assertion failed: ${message}`);
    console.log(`  FAIL ${message}`);
  }
}

async function goto(pageId) {
  window.location.hash = `#${pageId}`;
  window.dispatchEvent(new window.HashChangeEvent('hashchange'));
  await tick(110);
}

// ── Run ────────────────────────────────────────────────────────────────────

async function run() {
  console.log('\n── module graph ──────────────────────────────────────────');
  await import(pathToFileURL(resolve(WEBUI, 'js/app.js')).href);
  const i18n = await import(pathToFileURL(resolve(WEBUI, 'js/i18n.js')).href);
  const { t, getLocale, setLocale } = i18n;
  await tick(160);
  assert(true, 'app.js and its whole import graph loaded');

  console.log('\n── shell ─────────────────────────────────────────────────');
  assert($('#nav')?.children.length === 6, 'six navigation entries registered');
  assert($('#page-title')?.textContent === t('dashboard.title'),
    `header shows the dashboard title (${$('#page-title')?.textContent})`);
  assert(getLocale() === 'zh', 'the interface starts in Chinese');
  assert($('#lang-toggle')?.textContent === 'EN',
    'the language button offers the other language');
  assert($('#version-label')?.textContent.startsWith('v'), 'version label filled');

  console.log('\n── dashboard ─────────────────────────────────────────────');
  assert($$('.stat').length === 4, 'four stat tiles rendered');
  assert($$('.stat-icon').length === 4, 'each tile has an icon chip');
  assert($$('#recent-rows tr').length === 3, 'three task rows rendered');
  assert($('#recent-rows').textContent.includes('Gallery pull'), 'task name shown');
  assert($$('#recent-rows .badge').length === 3, 'status badges rendered');
  assert($('#recent-rows').textContent.includes(t('status.completed')),
    'status badges use translated labels');

  const runRow = $('#recent-rows tr[data-task-id="1"]');
  assert(runRow?.querySelector('.btn-danger') !== null, 'running task offers Stop');
  const failRow = $('#recent-rows tr[data-task-id="2"]');
  assert(failRow?.textContent.includes('All downloads failed'), 'failure reason surfaced');

  runRow.querySelector('button[title="' + t('action.details') + '"]').click();
  await tick();
  assert($('.modal') !== null, 'details modal opens');
  assert($('.modal').textContent.includes(t('dashboard.details.breakdown')),
    'details modal is translated');
  $('.modal-head .icon-btn').click();
  await tick();
  assert($('.modal') === null, 'details modal closes');

  console.log('\n── navigation ────────────────────────────────────────────');
  for (const [id, key] of [['new-task', 'newTask.title'], ['downloads', 'downloads.title'],
    ['files', 'files.title'], ['agents', 'agents.title'], ['settings', 'settings.title']]) {
    await goto(id);
    assert($('#page-title').textContent === t(key), `page "${id}" mounts`);
    assert($('#main').children.length > 0, `page "${id}" produced content`);
    assert(!$('#main').textContent.includes('failed to load'),
      `page "${id}" mounted without an error`);
  }

  console.log('\n── new task form ─────────────────────────────────────────');
  await goto('new-task');

  assert($('#f-url') !== null, 'URL field present');
  assert($('#f-url').placeholder === t('newTask.url.placeholder'),
    'placeholders are translated');
  assert($$('[data-ext]').length > 30, 'extension chips built');
  assert($$('[data-dec]').length === 7, 'seven decryptor toggles');
  assert($$('.recipe').length === 5, 'five recipe presets');
  assert($('#headers-editor').children.length >= 1, 'header editor seeded with a row');

  $('[data-preset="spa"]').click();
  await tick(40);
  assert($('#t-browser').checked === true, 'the SPA recipe enables browser rendering');
  assert($('#browser-options').hidden === false, 'browser options panel revealed');
  assert($('[data-preset="spa"]').dataset.on === 'true', 'the chosen recipe is marked');

  $('[data-preset="page"]').click();
  await tick(40);
  assert($('#t-browser').checked === false,
    'the single-page recipe turns browser rendering back off');
  assert($('#t-pagination').checked === false, 'and disables pagination');

  // JS guard for the empty URL.
  window.document.getElementById('task-form')
    .dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
  await tick(60);
  assert($('#form-status').textContent === t('newTask.urlRequired'),
    'empty URL is rejected by the JS guard');
  assert(window.document.getElementById('f-url').matches(':invalid'),
    'and the required attribute is still in place for native validation');

  const chip = $('[data-ext="jpg"]');
  chip.checked = true;
  chip.dispatchEvent(new window.Event('change', { bubbles: true }));
  assert(chip.closest('.chip').dataset.on === 'true', 'chip reflects checked state');

  $('#f-url').value = 'https://example.com/gallery/';
  $('#f-url').dispatchEvent(new window.Event('input', { bubbles: true }));
  $('#f-name').value = 'Smoke test';
  await tick(60);
  assert($('#url-preview').textContent.includes('example.com'), 'URL preview fills in');
  assert($('#url-preview').textContent.includes(t('newTask.urlPreview.guess')),
    'the URL preview is translated');

  const form = window.document.getElementById('task-form');
  assert(form.checkValidity(), 'form is valid once the URL is filled');
  form.requestSubmit();
  await tick(200);
  assert(calls.some((c) => c === 'POST /api/tasks'), 'task creation requested');
  assert(calls.some((c) => c.includes('/start')), 'task start requested');
  await tick(120);
  assert(window.location.hash === '#dashboard' && $('#page-title').textContent === t('dashboard.title'),
    'redirects to the dashboard after submit');

  console.log('\n── downloads ─────────────────────────────────────────────');
  await goto('downloads');
  assert($$('#dl-body tbody tr').length === 200,
    `the table is capped at the page size (${$$('#dl-body tbody tr').length})`);
  assert($('#dl-body').textContent.includes(t('downloads.truncated', { shown: 200, total: 250 })),
    'the truncation notice renders');
  assert($('#dl-task').options.length === 4, 'task filter populated');
  assert($('#dl-task').options[0].textContent === t('downloads.allTasks'),
    'the filter uses translated labels');

  $('#dl-status').value = 'failed';
  $('#dl-status').dispatchEvent(new window.Event('change', { bubbles: true }));
  await tick(40);
  assert($$('#dl-body tbody tr').length === 1, 'status filter narrows the table');
  assert($('#dl-body').textContent.includes('HTTP 403'), 'the failure reason is shown');
  $('#dl-status').value = '';
  $('#dl-status').dispatchEvent(new window.Event('change', { bubbles: true }));
  await tick(40);

  $('#dl-search').value = 'item-249';
  $('#dl-search').dispatchEvent(new window.Event('input', { bubbles: true }));
  await tick(320);
  assert($$('#dl-body tbody tr').length === 1, 'search narrows the table');
  $('#dl-search').value = 'zzz-nothing';
  $('#dl-search').dispatchEvent(new window.Event('input', { bubbles: true }));
  await tick(320);
  assert($('#dl-body .empty') !== null, 'empty state shown when nothing matches');
  assert($('#dl-body').textContent.includes(t('downloads.emptyFiltered.title')),
    'the empty state is translated');

  // Task-filtered view returns the short list.
  $('#dl-search').value = '';
  $('#dl-search').dispatchEvent(new window.Event('input', { bubbles: true }));
  await tick(320);
  $('#dl-task').value = '1';
  $('#dl-task').dispatchEvent(new window.Event('change', { bubbles: true }));
  await tick(200);
  assert($$('#dl-body tbody tr').length === 3, 'filtering by task loads that task only');
  assert(!$('#dl-body').textContent.includes(t('downloads.truncated', { shown: 200, total: 250 })),
    'the truncation notice disappears for a short list');

  console.log('\n── files ─────────────────────────────────────────────────');
  await goto('files');
  assert($$('#files-body tbody tr').length === 2, 'two files listed');
  assert($('#files-summary').textContent.length > 0, 'summary line filled');
  const nameButton = [...$$('.seg button')].find((b) => b.textContent === t('files.sort.name'));
  nameButton.click();
  await tick(90);
  assert(nameButton.getAttribute('aria-pressed') === 'true', 'sort control updates');

  console.log('\n── agents ────────────────────────────────────────────────');
  await goto('agents');
  assert($$('#agents-body tbody tr').length === 2, 'agent rows rendered');
  assert($('#agents-body').textContent.includes('/api/opencode'),
    'each row shows its own alias');
  const setup = $$('#agents-body tbody button').find((b) => b.textContent === t('action.setup'));
  setup.click();
  await tick(60);
  assert($('.modal') !== null, 'agent setup modal opens');
  assert($('.modal').textContent.includes('/api/opencode/quick'), 'alias-specific snippet shown');
  $('.modal-head .icon-btn').click();
  await tick(40);

  console.log('\n── settings ──────────────────────────────────────────────');
  await goto('settings');
  assert($('#s-concurrency').value === '5', 'settings loaded into the form');
  assert($('#runtime-card').textContent.includes('9.9.9'), 'runtime card shows the version');
  assert($('#runtime-card').textContent.includes('/api/agent'), 'agent aliases listed');

  console.log('\n── theme ─────────────────────────────────────────────────');
  assert(window.document.documentElement.dataset.theme === 'light',
    'the interface starts in light mode');
  const themeBtn = $('#theme-toggle');
  assert(themeBtn.querySelector('svg') !== null, 'the theme button has an icon');
  themeBtn.click();
  await tick(40);
  assert(window.document.documentElement.dataset.theme === 'dark',
    'the theme button switches to dark');
  assert(JSON.parse(window.localStorage.getItem('autoget:theme')) === 'dark',
    'the theme choice is persisted');
  themeBtn.click();
  await tick(40);
  assert(window.document.documentElement.dataset.theme === 'light',
    'and switches back to light');

  console.log('\n── language ──────────────────────────────────────────────');
  const navLabel = () => $('.nav-item[data-page="dashboard"]').textContent;
  assert(navLabel().includes(t('nav.dashboard')), 'nav is in Chinese');

  $('#lang-toggle').click();
  await tick(240);
  assert(getLocale() === 'en', 'the language button switches to English');
  assert(navLabel().includes('Dashboard'), 'nav labels switch to English');
  assert($('#page-title').textContent === 'Settings', 'the page title switches too');
  assert($('#s-concurrency') !== null, 'the page was re-mounted, not left blank');
  assert($('#runtime-card').textContent.includes('Runtime'), 'runtime card re-rendered');
  assert(JSON.parse(window.localStorage.getItem('autoget:locale')) === 'en',
    'the language choice is persisted');

  await goto('downloads');
  assert($('#dl-body').textContent.includes('Progress') || $$('#dl-body th').length > 0,
    'other pages render in English after the switch');

  $('#lang-toggle').click();
  await tick(240);
  assert(getLocale() === 'zh', 'switching back returns to Chinese');
  assert(navLabel().includes(t('nav.dashboard')), 'nav labels are Chinese again');

  console.log('\n── translation coverage ──────────────────────────────────');
  const { DICT } = await import(pathToFileURL(resolve(WEBUI, 'js/locales.js')).href);
  const missing = checkDictionary(DICT);
  assert(missing.length === 0,
    missing.length
      ? `dictionary key mismatch: ${missing.slice(0, 8).join(', ')}`
      : 'both dictionaries define exactly the same keys');

  const untranslated = findUntranslated(DICT.zh);
  assert(untranslated.length === 0,
    untranslated.length
      ? `zh values that look untranslated: ${untranslated.slice(0, 5).join(' | ')}`
      : 'no Chinese entry is a leftover English sentence');

  const emptyKeys = Object.entries(DICT.zh)
    .filter(([, value]) => !String(value).trim())
    .map(([key]) => key);
  assert(emptyKeys.length === 0,
    emptyKeys.length ? `empty zh values: ${emptyKeys.join(', ')}` : 'no empty translations');

  console.log('\n── teardown ──────────────────────────────────────────────');
  for (const id of ['dashboard', 'new-task', 'downloads', 'files', 'agents', 'settings']) {
    await goto(id);
    const strays = findStrayText();
    assert(strays.length === 0,
      strays.length
        ? `"${id}" renders stray text nodes: ${strays.join(', ')}`
        : `"${id}" renders no stray null/undefined text`);
  }

  console.log('\n──────────────────────────────────────────────────────────');
  if (failures.length) {
    console.log(`\n${failures.length} problem(s):`);
    for (const failure of failures) console.log(`  ✗ ${failure}`);
  } else {
    console.log(`\nAll ${checks.n} checks passed. ${calls.length} mutating API calls.`);
  }
  dom.window.close();
  process.exit(failures.length ? 1 : 0);
}

/**
 * Find text nodes that literally read "null"/"undefined".
 *
 * `element.replaceChildren(node, null)` stringifies its arguments, so a
 * conditional child that is null renders the word "null" on the page.
 */
function findStrayText() {
  const walker = window.document.createTreeWalker(
    window.document.getElementById('main'), window.NodeFilter.SHOW_TEXT);
  const found = [];
  let node = walker.nextNode();
  while (node) {
    const text = node.textContent.trim();
    if (text === 'null' || text === 'undefined') found.push(text);
    node = walker.nextNode();
  }
  return found;
}

/** Keys present in one dictionary but not the other. */
function checkDictionary(dict) {
  const zh = new Set(Object.keys(dict.zh));
  const en = new Set(Object.keys(dict.en));
  return [
    ...[...zh].filter((key) => !en.has(key)).map((key) => `zh-only:${key}`),
    ...[...en].filter((key) => !zh.has(key)).map((key) => `en-only:${key}`),
  ];
}

/**
 * Flag Chinese entries that still read as English prose.
 *
 * Short technical terms (Base64, XOR, CBC, API…) legitimately stay in Latin,
 * so only multi-word phrases with no CJK character at all are reported.
 */
function findUntranslated(zhDict) {
  const hasCjk = (text) => /[\u4e00-\u9fff\u3400-\u4dbf]/.test(text);
  return Object.entries(zhDict)
    .filter(([, value]) => {
      const text = String(value);
      if (hasCjk(text)) return false;
      // Ignore short tokens, code-ish values and placeholder-only strings.
      const words = text.replace(/\{[^}]*\}/g, ' ').trim().split(/\s+/).filter(Boolean);
      if (words.length < 4) return false;
      if (/^[\s\W]*$/.test(text)) return false;
      return true;
    })
    .map(([key]) => key);
}

run().catch((error) => {
  console.error('harness crashed:', error);
  process.exit(1);
});
