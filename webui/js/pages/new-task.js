/**
 * New task form.
 *
 * Built from declarative descriptors so validation, defaults and config
 * assembly all read from one place — no hand-written
 * `document.getElementById` calls scattered through `submit()`.
 *
 * Every user-facing string is a translation key resolved through `t()`.
 */

import {
  $, banner, bindToggle, h, icon, kvRow, store, toast,
} from '../core.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { navigate } from '../router.js';

/** Extension groups, keyed by their translation suffix. */
const MEDIA_PRESETS = {
  images: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'avif', 'heic', 'ico'],
  video: ['mp4', 'mkv', 'webm', 'mov', 'avi', 'flv', 'ts', 'm3u8', 'mpd'],
  audio: ['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'opus'],
  documents: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'epub', 'csv'],
  archives: ['zip', 'rar', '7z', 'tar', 'gz'],
  fonts: ['woff', 'woff2', 'ttf', 'otf', 'eot'],
};

const DECRYPTORS = [
  { name: 'base64', labelKey: 'newTask.dec.base64', descKey: 'newTask.dec.base64Desc' },
  { name: 'hex', labelKey: 'newTask.dec.hex', descKey: 'newTask.dec.hexDesc' },
  { name: 'aes', labelKey: 'newTask.dec.aes', descKey: 'newTask.dec.aesDesc', config: 'aes' },
  { name: 'xor', labelKey: 'newTask.dec.xor', descKey: 'newTask.dec.xorDesc', config: 'xor' },
  { name: 'url_sign', labelKey: 'newTask.dec.urlSign', descKey: 'newTask.dec.urlSignDesc' },
  { name: 'rot47', labelKey: 'newTask.dec.rot47', descKey: 'newTask.dec.rot47Desc' },
  { name: 'custom', labelKey: 'newTask.dec.custom', descKey: 'newTask.dec.customDesc',
    config: 'custom' },
];

/**
 * Recipes.
 *
 * Every preset lists *all* discovery/render toggles explicitly, and applying
 * one sets every toggle to the value in `config`. Anything left out counts as
 * off — otherwise picking "Single page" after "JavaScript app" would silently
 * keep browser rendering enabled.
 */
const PRESETS = [
  {
    id: 'page',
    labelKey: 'newTask.recipe.page',
    blurbKey: 'newTask.recipe.pageBlurb',
    config: {
      crawl_depth: 0, follow_pagination: false, follow_links: false,
      crawl_css: true, crawl_iframes: true, site_discovery: false,
      use_browser: false,
    },
  },
  {
    id: 'gallery',
    labelKey: 'newTask.recipe.gallery',
    blurbKey: 'newTask.recipe.galleryBlurb',
    config: {
      crawl_depth: 0, follow_pagination: true, follow_links: false,
      crawl_css: true, crawl_iframes: true, site_discovery: false,
      use_browser: false,
    },
  },
  {
    id: 'site',
    labelKey: 'newTask.recipe.site',
    blurbKey: 'newTask.recipe.siteBlurb',
    config: {
      crawl_depth: 4, follow_pagination: true, follow_links: true,
      crawl_css: true, crawl_iframes: true, site_discovery: true,
      use_browser: false, max_pages: 2000,
    },
  },
  {
    id: 'spa',
    labelKey: 'newTask.recipe.spa',
    blurbKey: 'newTask.recipe.spaBlurb',
    config: {
      crawl_depth: 1, follow_pagination: true, follow_links: false,
      crawl_css: true, crawl_iframes: true, site_discovery: false,
      use_browser: true,
    },
  },
  {
    id: 'stream',
    labelKey: 'newTask.recipe.stream',
    blurbKey: 'newTask.recipe.streamBlurb',
    config: {
      crawl_depth: 0, follow_pagination: false, follow_links: false,
      crawl_css: false, crawl_iframes: true, site_discovery: false,
      use_browser: true,
    },
    types: ['mp4', 'm3u8', 'mpd', 'webm', 'mkv', 'ts'],
  },
];

const DISCOVERY_TOGGLES = {
  't-pagination': 'follow_pagination',
  't-links': 'follow_links',
  't-sitemap': 'site_discovery',
  't-css': 'crawl_css',
  't-iframes': 'crawl_iframes',
  't-browser': 'use_browser',
};

let formState = null;

export const newTaskPage = {
  id: 'new-task',
  titleKey: 'newTask.title',
  subtitleKey: 'newTask.subtitle',
  icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',

  async mount(container) {
    formState = { files: {}, decryptors: {}, customExts: '', headers: [] };

    container.append(
      h('form#task-form', {
        onsubmit: (event) => { event.preventDefault(); submit(); },
      }, [
        buildTargetCard(),
        buildPresetCard(),
        buildFiltersCard(),
        buildDiscoveryCard(),
        buildExtractionCard(),
        buildDecryptorCard(),
        buildNetworkCard(),
        buildHeadersCard(),
        buildSubmitBar(),
      ]),
    );

    restoreDefaults();
    wireInteractions(container);

    return () => { formState = null; };
  },

  /** Primary action, pinned in the top bar so it is always reachable. */
  toolbar() {
    return h('div.btn-row', { style: { alignItems: 'center' } }, [
      h('span.submit-status#form-status'),
      h('button.btn.btn-primary#submit-btn', {
        type: 'button',
        onclick: () => submit(),
      }, [icon('zap'), t('newTask.submit')]),
    ]);
  },
};

// ── Sections ───────────────────────────────────────────────────────────────

function buildTargetCard() {
  return h('div.card', [
    h('div.card-head', [h('h2', t('newTask.target'))]),
    h('div.grid.grid-2', [
      field({
        label: t('newTask.name.label'), id: 'f-name',
        placeholder: t('newTask.name.placeholder'),
        hint: t('newTask.name.hint'),
      }),
      field({
        label: t('newTask.url.label'), id: 'f-url', type: 'text',
        placeholder: t('newTask.url.placeholder'), required: true,
        hint: t('newTask.url.hint'),
      }),
    ]),
    h('div#url-preview'),
  ]);
}

function buildPresetCard() {
  return h('div.card', [
    h('div.card-head', [
      h('h2', t('newTask.recipe')),
      h('span.card-sub', t('newTask.recipe.hint')),
    ]),
    h('div.grid.grid-3#preset-grid', PRESETS.map((preset) =>
      h('button.recipe', {
        type: 'button',
        dataset: { preset: preset.id, on: 'false' },
        onclick: () => applyPreset(preset.id),
      }, [
        h('span.recipe-dot'),
        h('span', [
          h('span.recipe-title', t(preset.labelKey)),
          h('span.recipe-desc', t(preset.blurbKey)),
        ]),
      ]))),
  ]);
}

function buildFiltersCard() {
  return h('div.card', [
    h('div.card-head', [
      h('h2', t('newTask.files')),
      h('span.card-sub', t('newTask.files.hint')),
      h('span.spacer'),
      h('button.btn.btn-sm.btn-ghost', {
        type: 'button', onclick: () => setAllTypes(true),
      }, t('action.all')),
      h('button.btn.btn-sm.btn-ghost', {
        type: 'button', onclick: () => setAllTypes(false),
      }, t('action.none')),
    ]),
    ...Object.entries(MEDIA_PRESETS).map(([group, extensions]) =>
      h('div', { style: { marginBottom: 'var(--s3)' } }, [
        h('div.nav-group', { style: { padding: '0 0 6px' } }, t(`newTask.files.${group}`)),
        h('div.chip-group', extensions.map((ext) => {
          const input = h('input', {
            type: 'checkbox',
            dataset: { ext },
            onchange: () => {
              formState.files[ext] = input.checked;
              bindToggle(input);
            },
          });
          formState.files[ext] = false;
          return h('label.chip', [input, `.${ext}`]);
        })),
      ])),
    field({
      label: t('newTask.files.custom'), id: 'f-custom-exts',
      placeholder: t('newTask.files.customPlaceholder'),
      hint: t('newTask.files.customHint'),
      oninput: (event) => { formState.customExts = event.target.value; },
    }),
  ]);
}

function buildDiscoveryCard() {
  return h('div.card', [
    h('div.card-head', [
      h('h2', t('newTask.discovery')),
      h('span.card-sub', t('newTask.discovery.hint')),
    ]),
    h('div.grid.grid-2', [
      numberField('f-depth', t('newTask.depth.label'), 0,
        { min: 0, max: 50, hint: t('newTask.depth.hint') }),
      numberField('f-max-pages', t('newTask.maxPages.label'), 500,
        { min: 1, max: 500000, hint: t('newTask.maxPages.hint') }),
      numberField('f-max-media', t('newTask.maxMedia.label'), 20000, { min: 1, max: 500000 }),
      numberField('f-max-links', t('newTask.maxLinks.label'), 20, { min: 1, max: 500 }),
    ]),
    field({
      label: t('newTask.paths.label'), id: 'f-paths',
      placeholder: t('newTask.paths.placeholder'), hint: t('newTask.paths.hint'),
    }),
    h('div.grid.grid-2', { style: { marginTop: 'var(--s3)' } }, [
      toggleField('t-pagination', 'newTask.opt.pagination', 'newTask.opt.paginationDesc', true),
      toggleField('t-links', 'newTask.opt.links', 'newTask.opt.linksDesc', false),
      toggleField('t-sitemap', 'newTask.opt.sitemap', 'newTask.opt.sitemapDesc', false),
      toggleField('t-css', 'newTask.opt.css', 'newTask.opt.cssDesc', true),
      toggleField('t-iframes', 'newTask.opt.iframes', 'newTask.opt.iframesDesc', true),
    ]),
  ]);
}

function buildExtractionCard() {
  return h('div.card', [
    h('div.card-head', [
      h('h2', t('newTask.render')),
      h('span.card-sub', t('newTask.render.hint')),
    ]),
    h('div.grid.grid-2', [
      toggleField('t-browser', 'newTask.opt.browser', 'newTask.opt.browserDesc', false),
      toggleField('t-base64', 'newTask.opt.base64', 'newTask.opt.base64Desc', false),
      toggleField('t-probe', 'newTask.opt.probe', 'newTask.opt.probeDesc', false),
    ]),
    h('div#browser-options', { hidden: true },
      h('div.grid.grid-2', { style: { marginTop: 'var(--s3)' } }, [
        numberField('f-scrolls', t('newTask.scrolls.label'), 30,
          { min: 1, max: 500, hint: t('newTask.scrolls.hint') }),
        numberField('f-scrolldelay', t('newTask.scrollDelay.label'), 1.5, { min: 0.2 }),
      ])),
  ]);
}

function buildDecryptorCard() {
  return h('div.card', [
    h('div.card-head', [
      h('h2', t('newTask.decryptors')),
      h('span.card-sub', t('newTask.decryptors.hint')),
    ]),
    h('div', DECRYPTORS.map((decryptor) => {
      const input = h('input', {
        type: 'checkbox',
        dataset: { dec: decryptor.name },
        onchange: () => {
          formState.decryptors[decryptor.name] = input.checked;
          bindToggle(input);
          const panel = $(`#dec-config-${decryptor.name}`);
          if (panel) panel.hidden = !input.checked;
        },
      });
      return h('div', { style: { marginBottom: 'var(--s3)' } }, [
        h('label.chip', [input, t(decryptor.labelKey)]),
        h('span', {
          style: {
            marginLeft: 'var(--s3)', fontSize: '11.5px', color: 'var(--text-faint)',
          },
        }, t(decryptor.descKey)),
        decryptor.config
          ? h('div', { id: `dec-config-${decryptor.name}`, hidden: true },
              h('div', { style: { marginTop: 'var(--s2)' } }, decryptorConfig(decryptor.config)))
          : null,
      ]);
    })),
  ]);
}

function decryptorConfig(kind) {
  if (kind === 'aes') {
    return h('div.grid.grid-3', [
      field({ label: t('newTask.dec.aesKey'), id: 'dec-aes-key', placeholder: '0123…' }),
      field({ label: t('newTask.dec.aesIv'), id: 'dec-aes-iv', placeholder: '0123…' }),
      h('div.field', [
        h('label', { for: 'dec-aes-mode' }, t('newTask.dec.aesMode')),
        h('select#dec-aes-mode', [
          h('option', { value: 'CBC' }, 'CBC'),
          h('option', { value: 'ECB' }, 'ECB'),
          h('option', { value: 'GCM' }, 'GCM'),
        ]),
      ]),
    ]);
  }
  if (kind === 'xor') {
    return field({ label: t('newTask.dec.xorKey'), id: 'dec-xor-key', placeholder: '55 或 0102ff' });
  }
  return field({
    label: t('newTask.dec.expr'), id: 'dec-custom-expr',
    placeholder: 'bytes(b ^ 0xFF for b in content)',
    hint: t('newTask.dec.exprHint'),
  });
}

function buildNetworkCard() {
  return h('div.card', [
    h('div.card-head', [h('h2', t('newTask.network'))]),
    h('div.grid.grid-2', [
      numberField('f-concurrency', t('newTask.concurrency.label'), 5,
        { min: 1, max: 50, hint: t('newTask.concurrency.hint') }),
      numberField('f-delay', t('newTask.delay.label'), 0.5,
        { min: 0, hint: t('newTask.delay.hint') }),
      numberField('f-timeout', t('newTask.timeout.label'), 30, { min: 3, max: 600 }),
      numberField('f-retries', t('newTask.retries.label'), 3, { min: 0, max: 10 }),
      numberField('f-maxsize', t('newTask.maxSize.label'), 500,
        { min: 0, hint: t('newTask.maxSize.hint') }),
      field({ label: t('newTask.output.label'), id: 'f-output', placeholder: './downloads' }),
    ]),
    field({
      label: t('newTask.proxy.label'), id: 'f-proxy',
      placeholder: t('newTask.proxy.placeholder'), hint: t('newTask.proxy.hint'),
    }),
  ]);
}

function buildHeadersCard() {
  return h('div.card', [
    h('div.card-head', [
      h('h2', t('newTask.headers')),
      h('span.card-sub', t('newTask.headers.hint')),
      h('span.spacer'),
      h('button.btn.btn-sm.btn-ghost', {
        type: 'button', onclick: () => addHeaderRow('', ''),
      }, [icon('plus'), t('action.add')]),
    ]),
    h('div#headers-editor'),
  ]);
}

function buildSubmitBar() {
  // The primary action and the status line live in the sticky top bar (see
  // `toolbar()` below) so a long form is never covered by a floating bar.
  return h('div.btn-row', { style: { margin: '0 0 var(--s6)' } }, [
    h('button.btn.btn-ghost', {
      type: 'button',
      onclick: () => { resetForm(); toast(t('newTask.reset'), { timeout: 1400 }); },
    }, [icon('refresh'), t('action.reset')]),
  ]);
}

// ── Field factories ────────────────────────────────────────────────────────

function field({ label, id, type = 'text', placeholder = '', hint = '',
                 required = false, oninput = null }) {
  return h('div.field', [
    h('label', { for: id }, label),
    h('input', { id, type, placeholder, required, oninput, autocomplete: 'off' }),
    hint ? h('div.field-hint', hint) : null,
  ]);
}

/**
 * Numeric input.
 *
 * `step` defaults to "any": the values here are user-chosen quantities, and a
 * fixed step silently blocks form submission whenever the default value is not
 * on the step grid (e.g. `min=0.2 step=0.5 value=1.5`). Range is enforced by
 * `min`/`max` plus the clamp in `collectConfig()`.
 */
function numberField(id, label, value, { min = 0, max = null, step = 'any', hint = '' } = {}) {
  return h('div.field', [
    h('label', { for: id }, label),
    h('input', { id, type: 'number', value, min, max, step }),
    hint ? h('div.field-hint', hint) : null,
  ]);
}

function toggleField(id, titleKey, descKey, checked = false) {
  const input = h('input', { type: 'checkbox', id, checked });
  const wrap = h('label.switch', { for: id }, [
    input,
    h('div.switch-track'),
    h('div.switch-body', [
      h('div.switch-title', t(titleKey)),
      h('div.switch-desc', t(descKey)),
    ]),
  ]);
  queueMicrotask(() => bindToggle(input));
  return wrap;
}

// ── Behaviour ──────────────────────────────────────────────────────────────

function wireInteractions(container) {
  const browserToggle = $('#t-browser', container);
  browserToggle?.addEventListener('change', () => {
    const panel = $('#browser-options', container);
    if (panel) panel.hidden = !browserToggle.checked;
  });

  const urlInput = $('#f-url', container);
  urlInput?.addEventListener('input', () => renderUrlPreview(urlInput.value.trim()));

  container.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const input = event.target;
    if (input.tagName !== 'INPUT' || !input.closest('#headers-editor')) return;
    event.preventDefault();
    const editor = $('#headers-editor', container);
    if (input.closest('.kv-row') === editor.lastElementChild) addHeaderRow('', '');
  });

  addHeaderRow('', '');
}

function addHeaderRow(key, value) {
  const editor = $('#headers-editor');
  if (!editor) return;

  const keyInput = h('input', {
    type: 'text', placeholder: t('newTask.header.name'), value: key,
    autocomplete: 'off', oninput: syncHeaders,
  });
  const valueInput = h('input', {
    type: 'text', placeholder: t('newTask.header.value'), value,
    autocomplete: 'off', oninput: syncHeaders,
  });
  const row = h('div.kv-row', [
    keyInput,
    valueInput,
    h('button.kv-remove', {
      type: 'button',
      'aria-label': t('action.delete'),
      onclick: () => { row.remove(); syncHeaders(); },
    }, icon('close')),
  ]);

  editor.append(row);
  syncHeaders();
}

function syncHeaders() {
  const editor = $('#headers-editor');
  if (!editor || !formState) return;
  formState.headers = [...editor.querySelectorAll('.kv-row')].map((row) => {
    const [key, value] = row.querySelectorAll('input');
    return { key: key.value.trim(), value: value.value.trim() };
  });
}

function setAllTypes(checked) {
  document.querySelectorAll('[data-ext]').forEach((input) => {
    input.checked = checked;
    if (formState) formState.files[input.dataset.ext] = checked;
    bindToggle(input);
  });
}

function applyPreset(presetId) {
  const preset = PRESETS.find((item) => item.id === presetId);
  if (!preset || !formState) return;

  document.querySelectorAll('[data-preset]').forEach((node) => {
    node.dataset.on = String(node.dataset.preset === presetId);
  });

  for (const [inputId, key] of Object.entries(DISCOVERY_TOGGLES)) {
    const input = document.getElementById(inputId);
    if (!input) continue;
    input.checked = Boolean(preset.config[key]);
    bindToggle(input);
  }

  const numeric = { 'f-depth': 'crawl_depth', 'f-max-pages': 'max_pages' };
  for (const [inputId, key] of Object.entries(numeric)) {
    const input = document.getElementById(inputId);
    if (input && key in preset.config) input.value = preset.config[key];
  }

  if (preset.types) {
    setAllTypes(false);
    document.querySelectorAll('[data-ext]').forEach((input) => {
      if (preset.types.includes(input.dataset.ext)) {
        input.checked = true;
        formState.files[input.dataset.ext] = true;
        bindToggle(input);
      }
    });
  }

  const browserPanel = $('#browser-options');
  if (browserPanel) browserPanel.hidden = !$('#t-browser')?.checked;

  toast(t('newTask.recipe.applied', { name: t(preset.labelKey) }),
    { type: 'info', timeout: 1800 });
}

function renderUrlPreview(rawUrl) {
  const node = $('#url-preview');
  if (!node) return;
  node.replaceChildren();
  if (!rawUrl) return;

  let parsed;
  try {
    parsed = new URL(rawUrl.includes('://') ? rawUrl : `https://${rawUrl}`);
  } catch {
    node.append(banner({
      tone: 'warning',
      title: t('newTask.urlInvalid.title'),
      message: t('newTask.urlInvalid.message'),
    }));
    return;
  }

  node.append(h('div.kv-list', { style: { marginTop: 'var(--s2)' } }, [
    kvRow(t('newTask.urlPreview.host'), parsed.hostname),
    kvRow(t('newTask.urlPreview.path'), parsed.pathname || '/'),
    kvRow(t('newTask.urlPreview.guess'), guessTarget(parsed)),
  ]));
}

function guessTarget(parsed) {
  const path = parsed.pathname.toLowerCase();
  if (/(gallery|photos?|images?|album)/.test(path)) return t('newTask.guess.gallery');
  if (/(video|watch|player|movie|episode|stream)/.test(path)) return t('newTask.guess.video');
  if (/(blog|post|article|news)/.test(path)) return t('newTask.guess.article');
  if (/(forum|thread|topic)/.test(path)) return t('newTask.guess.forum');
  if (/(download|files?)/.test(path)) return t('newTask.guess.download');
  return t('newTask.guess.page');
}

// ── Defaults persistence ───────────────────────────────────────────────────

function restoreDefaults() {
  const saved = store.get('defaults', null);
  if (!saved) return;
  const apply = (id, value) => {
    const input = document.getElementById(id);
    if (input && value !== undefined && value !== null && value !== '') input.value = value;
  };
  apply('f-concurrency', saved.concurrency);
  apply('f-delay', saved.delay);
  apply('f-timeout', saved.timeout);
  apply('f-retries', saved.retries);
  apply('f-maxsize', saved.maxSize);
  apply('f-output', saved.outputDir);
  apply('f-max-pages', saved.maxPages);
}

function persistDefaults(config) {
  store.set('defaults', {
    concurrency: config.concurrency,
    delay: config.request_delay_sec,
    timeout: config.request_timeout_sec,
    retries: config.max_retries,
    maxSize: config.max_file_size_mb,
    outputDir: config.output_dir,
    maxPages: config.max_pages,
  });
}

// ── Submit ─────────────────────────────────────────────────────────────────

function readNumber(id, fallback) {
  const value = Number(document.getElementById(id)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function readText(id, fallback = '') {
  const value = document.getElementById(id)?.value;
  return value === undefined || value === null ? fallback : String(value).trim();
}

function readToggle(id) {
  return Boolean(document.getElementById(id)?.checked);
}

function collectConfig() {
  const selectedExts = [...document.querySelectorAll('[data-ext]:checked')]
    .map((input) => input.dataset.ext);
  const customExts = readText('f-custom-exts')
    .split(',').map((value) => value.trim().replace(/^\./, '')).filter(Boolean);
  const extensions = [...new Set([...selectedExts, ...customExts])];

  const decryptors = [...document.querySelectorAll('[data-dec]:checked')]
    .map((input) => input.dataset.dec);
  const decryptorOpts = {};
  if (decryptors.includes('aes')) {
    decryptorOpts.aes = {
      key: readText('dec-aes-key'),
      iv: readText('dec-aes-iv'),
      mode: readText('dec-aes-mode', 'CBC').toLowerCase(),
    };
  }
  if (decryptors.includes('xor')) decryptorOpts.xor_key = readText('dec-xor-key');
  if (decryptors.includes('custom')) decryptorOpts.custom_expr = readText('dec-custom-expr');

  syncHeaders();
  const headers = Object.fromEntries(
    (formState?.headers || [])
      .filter((pair) => pair.key && pair.value)
      .map((pair) => [pair.key, pair.value]));

  const config = {
    concurrency: clamp(readNumber('f-concurrency', 5), 1, 50),
    request_delay_sec: Math.max(0, readNumber('f-delay', 0.5)),
    request_timeout_sec: clamp(readNumber('f-timeout', 30), 3, 600),
    max_retries: clamp(readNumber('f-retries', 3), 0, 10),
    max_file_size_mb: Math.max(0, readNumber('f-maxsize', 500)),
    output_dir: readText('f-output', './downloads') || './downloads',

    crawl_depth: clamp(readNumber('f-depth', 0), 0, 50),
    max_pages: clamp(readNumber('f-max-pages', 500), 1, 500000),
    max_media: clamp(readNumber('f-max-media', 20000), 1, 500000),
    max_links_per_page: clamp(readNumber('f-max-links', 20), 1, 500),

    follow_pagination: readToggle('t-pagination'),
    follow_links: readToggle('t-links'),
    site_discovery: readToggle('t-sitemap'),
    crawl_css: readToggle('t-css'),
    crawl_iframes: readToggle('t-iframes'),

    use_browser: readToggle('t-browser'),
    extract_base64: readToggle('t-base64'),
    probe_links: readToggle('t-probe'),

    decryptors,
    decryptor_opts: decryptorOpts,
    custom_headers: headers,
  };

  if (config.use_browser) {
    config.scroll_page = true;
    config.max_scrolls = clamp(readNumber('f-scrolls', 30), 1, 500);
    config.scroll_delay = Math.max(0.2, readNumber('f-scrolldelay', 1.5));
  }
  if (extensions.length) config.url_filters = { include: extensions.map((e) => `*.${e}`) };

  const paths = readText('f-paths').split(',').map((v) => v.trim()).filter(Boolean);
  if (paths.length) config.allowed_paths = paths;

  const proxy = readText('f-proxy');
  if (proxy) config.proxy = proxy;

  return config;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

async function submit() {
  const button = $('#submit-btn');

  const url = readText('f-url');
  if (!url) {
    setStatus(t('newTask.urlRequired'), 'error');
    document.getElementById('f-url')?.focus();
    return;
  }

  const config = collectConfig();
  const name = readText('f-name') || defaultName(url);

  button.disabled = true;
  button.replaceChildren(h('span.spinner'), t('newTask.submitting'));
  setStatus(t('newTask.submitting'));

  try {
    const created = await api.tasks.create(name, url, config);
    const taskId = created?.task?.id;
    if (!taskId) throw new Error(t('newTask.noTaskId'));

    setStatus(t('newTask.starting'));
    await api.tasks.start(taskId);

    persistDefaults(config);
    toast(t('newTask.submitted'), { type: 'success', title: name, timeout: 2600 });
    navigate('dashboard');
  } catch (error) {
    setStatus(error.message, 'error');
    toast(error.message, { type: 'error', title: t('newTask.submitFailed') });
  } finally {
    button.disabled = false;
    button.replaceChildren(icon('zap'), t('newTask.submit'));
  }
}

function setStatus(message, tone = 'muted') {
  const node = $('#form-status');
  if (!node) return;
  node.textContent = message;
  node.dataset.tone = tone === 'error' ? 'error' : '';
}

function defaultName(url) {
  try {
    const parsed = new URL(url.includes('://') ? url : `https://${url}`);
    return parsed.hostname + (parsed.pathname !== '/' ? parsed.pathname : '');
  } catch {
    return url.slice(0, 60);
  }
}

function resetForm() {
  document.getElementById('task-form')?.reset();
  document.querySelectorAll('[data-ext], [data-dec]').forEach((input) => {
    input.checked = false;
    bindToggle(input);
  });
  document.querySelectorAll('[data-preset]').forEach((node) => { node.dataset.on = 'false'; });
  $('#headers-editor')?.replaceChildren();
  addHeaderRow('', '');
  if (formState) {
    formState.files = {};
    formState.decryptors = {};
  }
  $('#url-preview')?.replaceChildren();
  setStatus('');
  restoreDefaults();
}
