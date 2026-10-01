/** Settings: server defaults, credentials, and runtime facts. */

import {
  $, banner, codeBlock, copyText, h, icon, kvRow, store, toast,
} from '../core.js';
import { api } from '../api.js';
import { t } from '../i18n.js';

const NUMBER_FIELDS = [
  { key: 'default_concurrency', id: 's-concurrency', labelKey: 'settings.concurrency',
    hintKey: 'settings.concurrency.hint' },
  { key: 'default_crawl_depth', id: 's-depth', labelKey: 'settings.depth',
    hintKey: 'settings.depth.hint' },
  { key: 'default_max_pages', id: 's-maxpages', labelKey: 'settings.maxPages' },
];

const TEXT_FIELDS = [
  { key: 'default_output_dir', id: 's-output', labelKey: 'settings.output',
    hintKey: 'settings.output.hint' },
  { key: 'proxy', id: 's-proxy', labelKey: 'settings.proxy',
    placeholder: 'http://127.0.0.1:7890' },
];

const SECRET_FIELDS = [
  { key: 'aes_key', id: 's-aes-key', labelKey: 'settings.aesKey',
    placeholderKey: 'settings.aesKeyPlaceholder' },
  { key: 'aes_iv', id: 's-aes-iv', labelKey: 'settings.aesIv',
    placeholderKey: 'settings.aesIvPlaceholder' },
];

export const settingsPage = {
  id: 'settings',
  titleKey: 'settings.title',
  subtitleKey: 'settings.subtitle',
  icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',

  async mount(container) {
    container.append(
      h('form#settings-form', {
        onsubmit: (event) => { event.preventDefault(); save(); },
      }, [
        h('div.card', [
          h('div.card-head', [
            h('h2', t('settings.defaults')),
            h('span.card-sub', t('settings.defaults.hint')),
          ]),
          h('div.grid.grid-2', [
            ...NUMBER_FIELDS.map((field) => h('div.field', [
              h('label', { for: field.id }, t(field.labelKey)),
              h('input', { id: field.id, type: 'number', min: '0' }),
              field.hintKey ? h('div.field-hint', t(field.hintKey)) : null,
            ])),
            ...TEXT_FIELDS.map((field) => h('div.field', [
              h('label', { for: field.id }, t(field.labelKey)),
              h('input', { id: field.id, type: 'text', placeholder: field.placeholder || '' }),
              field.hintKey ? h('div.field-hint', t(field.hintKey)) : null,
            ])),
          ]),
        ]),

        h('div.card', [
          h('div.card-head', [
            h('h2', t('settings.aes')),
            h('span.card-sub', t('settings.aes.hint')),
          ]),
          h('div.grid.grid-2', SECRET_FIELDS.map((field) => h('div.field', [
            h('label', { for: field.id }, t(field.labelKey)),
            h('div.input-row', [
              h('input', {
                id: field.id, type: 'password',
                placeholder: t(field.placeholderKey), autocomplete: 'new-password',
              }),
              h('button.btn.btn-ghost', {
                type: 'button',
                'aria-label': t('settings.showValue'),
                title: t('settings.showValue'),
                onclick: (event) => {
                  const input = $(`#${field.id}`);
                  const shown = input.type === 'text';
                  input.type = shown ? 'password' : 'text';
                  event.currentTarget.replaceChildren(icon(shown ? 'shield' : 'info'));
                },
              }, icon('info')),
            ]),
            h('div.field-hint', t('settings.aesStored')),
          ]))),
        ]),

        h('div.card', [
          h('div.card-head', [
            h('h2', t('settings.token')),
            h('span.card-sub', t('settings.token.hint')),
          ]),
          h('div.field', [
            h('label', { for: 's-token' }, t('settings.token')),
            h('div.input-row', [
              h('input', {
                id: 's-token', type: 'password', autocomplete: 'off',
                placeholder: t('settings.token.placeholder'),
              }),
              h('button.btn', {
                type: 'button',
                onclick: () => {
                  store.remove('token');
                  const input = $('#s-token');
                  if (input) input.value = '';
                  toast(t('settings.token.cleared'), { type: 'success' });
                },
              }, t('settings.token.clear')),
            ]),
            h('div.field-hint', t('settings.token.stored')),
          ]),
          h('div.btn-row', { style: { marginTop: 'var(--s3)' } }, [
            h('button.btn', { type: 'button', onclick: saveToken },
              [icon('check'), t('settings.token.save')]),
          ]),
        ]),

        h('div.btn-row', { style: { margin: '0 0 var(--s6)' } }, [
          h('button.btn.btn-primary.btn-lg#save-settings', { type: 'submit' },
            [icon('check'), t('action.save')]),
          h('button.btn.btn-ghost', { type: 'button', onclick: () => load(true) },
            [icon('refresh'), t('action.reload')]),
        ]),
      ]),
      h('div#runtime-card'),
    );

    await Promise.all([load(), renderRuntime()]);
  },
};

async function load(showToast = false) {
  try {
    const { settings } = await api.settings.get();
    for (const field of [...NUMBER_FIELDS, ...TEXT_FIELDS, ...SECRET_FIELDS]) {
      const input = document.getElementById(field.id);
      if (input) input.value = settings[field.key] ?? '';
    }
    const tokenInput = $('#s-token');
    if (tokenInput) tokenInput.value = store.get('token', '');
    if (showToast) toast(t('settings.reloaded'), { timeout: 1500 });
  } catch (error) {
    toast(error.message, { type: 'error', title: t('settings.loadFailed') });
  }
}

async function save() {
  const button = $('#save-settings');
  if (button) {
    button.disabled = true;
    button.replaceChildren(h('span.spinner'), t('action.saving'));
  }

  const payload = {};
  for (const field of [...NUMBER_FIELDS, ...TEXT_FIELDS, ...SECRET_FIELDS]) {
    const input = document.getElementById(field.id);
    if (input) payload[field.key] = input.value.trim();
  }

  try {
    await api.settings.save(payload);
    toast(t('settings.saved'), { type: 'success' });
    await load();
  } catch (error) {
    toast(error.message, { type: 'error', title: t('settings.saveFailed') });
  } finally {
    if (button) {
      button.disabled = false;
      button.replaceChildren(icon('check'), t('action.save'));
    }
  }
}

function saveToken() {
  const input = $('#s-token');
  if (!input) return;
  const value = input.value.trim();
  if (value) {
    store.set('token', value);
    toast(t('settings.token.saved'), { type: 'success' });
  } else {
    store.remove('token');
    toast(t('settings.token.cleared'), { timeout: 1500 });
  }
  // The token affects every subsequent request, including the WebSocket.
  window.setTimeout(() => location.reload(), 700);
}

async function renderRuntime() {
  const host = $('#runtime-card');
  if (!host) return;

  let info;
  try {
    info = await api.system();
  } catch {
    host.append(banner({
      tone: 'danger',
      title: t('settings.unreachable.title'),
      message: t('settings.unreachable.message'),
    }));
    return;
  }

  const aliases = info.agent_aliases || [];

  host.append(h('div.card', [
    h('div.card-head', [
      h('h2', t('settings.runtime')),
      h('span.card-sub', t('settings.runtime.hint')),
      h('span.spacer'),
      h('button.btn.btn-sm', {
        type: 'button',
        onclick: () => copyText(aliases.join('\n'), t('settings.aliasesCopied')),
      }, [icon('copy'), t('action.copy')]),
    ]),
    h('div.kv-list', [
      kvRow(t('settings.version'), `v${info.version}`),
      kvRow(t('settings.python'), info.python),
      kvRow(t('settings.auth'), info.auth_required
        ? h('span.badge.badge-completed', t('settings.authRequired'))
        : h('span.badge.badge-paused', t('settings.authOpen'))),
      kvRow(t('settings.downloadsDir'), h('span.mono', info.downloads_dir)),
      kvRow(t('settings.runningTasks'), String((info.running_tasks || []).length)),
      kvRow(t('settings.agentCount'), String(info.agent_count)),
    ]),
    h('h3', { style: { margin: 'var(--s5) 0 var(--s3)', fontSize: '13px' } },
      t('settings.aliases')),
    h('div.chip-group', aliases.map((alias) => h('span.tag', alias))),
    h('p', {
      style: { marginTop: 'var(--s3)', fontSize: '12.5px', color: 'var(--text-muted)' },
    }, t('settings.aliasesHint')),
    codeBlock(`curl ${location.origin}${aliases[0] || '/api/agent'}/manifest`),
  ]));
}
