/** Files: what actually landed on disk, with preview and delete. */

import {
  $, confirmDialog, debounce, emptyState, formatBytes, formatDateTime, h, icon,
  kindIcon, skeletonList, toast,
} from '../core.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { setNavCount } from '../router.js';

let state = { sort: 'mtime', search: '', directory: '', rows: [] };
let searchInput = null;

export const filesPage = {
  id: 'files',
  titleKey: 'files.title',
  subtitleKey: 'files.subtitle',
  icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',

  async mount(container) {
    state = { sort: 'mtime', search: '', directory: '', rows: [] };

    searchInput = h('input#file-search', {
      type: 'search', placeholder: t('files.searchPlaceholder'), autocomplete: 'off',
      oninput: debounce((event) => { state.search = event.target.value; load(); }, 250),
    });

    const sortControl = h('div.seg', [
      segButton('mtime', t('files.sort.mtime')),
      segButton('name', t('files.sort.name')),
      segButton('size', t('files.sort.size')),
    ]);

    container.append(
      h('div.card', [
        h('div.grid.grid-2', [
          h('div.field', { style: { marginBottom: 0 } }, [
            h('label', { for: 'file-search' }, t('action.search')),
            searchInput,
          ]),
          h('div.field', { style: { marginBottom: 0 } }, [
            h('span.field-label', t('files.sort')),
            sortControl,
          ]),
        ]),
        h('div.btn-row', { style: { marginTop: 'var(--s4)' } }, [
          h('button.btn.btn-sm', { type: 'button', onclick: () => load(true) },
            [icon('refresh'), t('action.rescan')]),
          h('div#files-summary', {
            style: { marginLeft: 'auto', fontSize: '12px', color: 'var(--text-muted)' },
          }),
        ]),
      ]),
      h('div.card.flush', h('div#files-body', skeletonList(6))),
    );

    await load();

    return () => { searchInput = null; };
  },
};

function segButton(value, label) {
  return h('button', {
    type: 'button',
    'aria-pressed': String(state.sort === value),
    onclick: (event) => {
      state.sort = value;
      event.currentTarget.parentElement
        .querySelectorAll('button')
        .forEach((node) => node.setAttribute('aria-pressed', String(node === event.currentTarget)));
      load();
    },
  }, label);
}

async function load(showToast = false) {
  const body = $('#files-body');
  if (!body) return;
  body.replaceChildren(skeletonList(6));

  try {
    const result = await api.files.list({ sort: state.sort, search: state.search });
    state.rows = result.files || [];
    state.directory = result.directory || '';
    render(result);
    setNavCount('files', state.rows.length);
    if (showToast) toast(t('files.found', { n: state.rows.length }), { timeout: 1500 });
  } catch (error) {
    body.replaceChildren(emptyState({
      iconName: 'alert',
      title: t('files.error.title'),
      message: error.message,
    }));
    if (showToast) toast(error.message, { type: 'error' });
  }
}

function render(result) {
  const body = $('#files-body');
  if (!body) return;

  const summary = $('#files-summary');
  if (summary) {
    summary.textContent = state.rows.length
      ? t('files.summary', {
          n: state.rows.length, size: formatBytes(result?.total_size || 0),
        })
      : '';
    summary.title = state.directory || '';
  }

  if (!state.rows.length) {
    body.replaceChildren(emptyState({
      iconName: state.search ? 'search' : 'folder',
      title: t(state.search ? 'files.emptyFiltered.title' : 'files.empty.title'),
      message: state.search
        ? t('files.emptyFiltered.message')
        : t('files.empty.message', { dir: state.directory || './downloads' }),
    }));
    return;
  }

  body.replaceChildren(h('div.table-wrap', h('table', [
    h('thead', h('tr', [
      h('th', { style: { width: '38px' } }, ''),
      h('th', t('files.col.name')),
      h('th', t('files.col.size')),
      h('th', t('files.col.written')),
      h('th.actions', ''),
    ])),
    h('tbody', state.rows.map(buildRow)),
  ])));
}

function buildRow(file) {
  const canPreview = /^(image|video|audio)\//.test(file.mime || '')
    || /\.(png|jpe?g|gif|webp|avif|svg|mp4|webm|mp3|m4a|ogg)$/i.test(file.name);

  return h('tr', [
    h('td', kindIcon(file.name)),
    h('td', [
      h('div.cell-strong.truncate', { title: file.name }, file.name),
      h('div.cell-mono.truncate', { title: file.path }, file.path),
    ]),
    h('td.num', file.size_human || formatBytes(file.size)),
    h('td', { style: { color: 'var(--text-muted)', fontSize: '12px' } },
      formatDateTime(new Date(file.mtime * 1000).toISOString())),
    h('td.actions', [
      canPreview
        ? h('a.btn.btn-sm.btn-ghost', {
            href: api.files.url(file.path, { inline: true }),
            target: '_blank', rel: 'noopener noreferrer', title: t('action.openNewTab'),
          }, icon('external'))
        : null,
      h('a.btn.btn-sm.btn-primary', {
        href: api.files.url(file.path),
        download: file.name,
      }, [icon('download'), t('action.save2pc')]),
      h('button.btn.btn-sm.btn-ghost', {
        type: 'button', title: t('action.deleteDisk'), 'aria-label': t('action.deleteDisk'),
        onclick: () => remove(file),
      }, icon('trash')),
    ]),
  ]);
}

async function remove(file) {
  const ok = await confirmDialog({
    title: t('files.delete.title'),
    message: t('files.delete.message', {
      name: file.name, size: file.size_human || formatBytes(file.size),
    }),
    confirmLabel: t('action.delete'),
    danger: true,
  });
  if (!ok) return;

  try {
    await api.files.remove(file.path);
    toast(t('files.deleted'), { type: 'success' });
    await load();
  } catch (error) {
    toast(error.message, { type: 'error' });
  }
}

export function focusFilesSearch() {
  searchInput?.focus();
  searchInput?.select();
}
