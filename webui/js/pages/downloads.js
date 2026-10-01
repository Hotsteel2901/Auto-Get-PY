/** Downloads: every file the scraper has fetched, filterable and searchable. */

import {
  $, copyText, debounce, emptyState, formatBytes, formatPercent, h,
  icon, kindIcon, mount, progressBar, skeletonList, statusBadge, toast,
} from '../core.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { getFileProgress, onLiveChange } from '../live.js';
import { setNavCount } from '../router.js';

const PAGE_SIZE = 200;

let state = { taskId: '', statusFilter: '', search: '', rows: [] };
let unsubscribeLive = null;
let searchInput = null;

export const downloadsPage = {
  id: 'downloads',
  titleKey: 'downloads.title',
  subtitleKey: 'downloads.subtitle',
  icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 19h16"/></svg>',

  async mount(container) {
    state = { taskId: '', statusFilter: '', search: '', rows: [] };

    const taskSelect = h('select#dl-task', {
      onchange: (event) => { state.taskId = event.target.value; load(); },
    }, h('option', { value: '' }, t('downloads.allTasks')));

    const statusSelect = h('select#dl-status', {
      onchange: (event) => { state.statusFilter = event.target.value; render(); },
    }, [
      h('option', { value: '' }, t('downloads.anyStatus')),
      h('option', { value: 'completed' }, t('status.completed')),
      h('option', { value: 'failed' }, t('status.failed')),
      h('option', { value: 'downloading' }, t('status.downloading')),
      h('option', { value: 'pending' }, t('status.pending')),
    ]);

    searchInput = h('input#dl-search', {
      type: 'search', placeholder: t('downloads.searchPlaceholder'), autocomplete: 'off',
      oninput: debounce((event) => {
        state.search = event.target.value.toLowerCase();
        render();
      }, 200),
    });

    container.append(
      h('div.card', [
        h('div.grid.grid-3', [
          h('div.field', { style: { marginBottom: 0 } },
            [h('label', { for: 'dl-task' }, t('downloads.task')), taskSelect]),
          h('div.field', { style: { marginBottom: 0 } },
            [h('label', { for: 'dl-status' }, t('downloads.status')), statusSelect]),
          h('div.field', { style: { marginBottom: 0 } },
            [h('label', { for: 'dl-search' }, t('action.search')), searchInput]),
        ]),
        h('div.btn-row', { style: { marginTop: 'var(--s4)' } }, [
          h('button.btn.btn-sm', { type: 'button', onclick: () => load(true) },
            [icon('refresh'), t('action.refresh')]),
          h('button.btn.btn-sm.btn-ghost', { type: 'button', onclick: exportCsv },
            [icon('download'), t('action.export')]),
          h('div#dl-summary', {
            style: { marginLeft: 'auto', fontSize: '12px', color: 'var(--text-muted)' },
          }),
        ]),
      ]),
      h('div.card.flush', h('div#dl-body', skeletonList(6))),
    );

    await populateTasks();
    await load();
    unsubscribeLive = onLiveChange(applyLiveProgress);

    return () => { unsubscribeLive?.(); searchInput = null; };
  },
};

async function populateTasks() {
  try {
    const { tasks } = await api.tasks.list({ limit: 200 });
    const select = $('#dl-task');
    if (!select) return;
    const current = select.value;
    select.replaceChildren(
      h('option', { value: '' }, t('downloads.allTasks')),
      ...tasks.map((task) => h('option', { value: String(task.id) },
        `#${task.id} · ${task.name || task.url}`)),
    );
    select.value = current;
  } catch (error) {
    toast(error.message, { type: 'error' });
  }
}

async function load(showToast = false) {
  const body = $('#dl-body');
  if (!body) return;
  body.replaceChildren(skeletonList(6));

  try {
    const rows = state.taskId
      ? (await api.downloads.forTask(Number(state.taskId))).downloads || []
      : (await api.downloads.all({ limit: 1000 })).downloads || [];

    state.rows = rows;
    render();
    setNavCount('downloads', rows.filter((row) => row.status === 'downloading').length);
    if (showToast) toast(`${rows.length}`, { timeout: 1600 });
  } catch (error) {
    body.replaceChildren(emptyState({
      iconName: 'alert',
      title: t('downloads.error.title'),
      message: error.message,
    }));
    if (showToast) toast(error.message, { type: 'error' });
  }
}

function filteredRows() {
  const { search, statusFilter } = state;
  return state.rows.filter((row) => {
    if (statusFilter && row.status !== statusFilter) return false;
    if (!search) return true;
    return (row.filename || '').toLowerCase().includes(search)
      || (row.url || '').toLowerCase().includes(search);
  });
}

function render() {
  const body = $('#dl-body');
  if (!body) return;
  const rows = filteredRows();

  const summary = $('#dl-summary');
  if (summary) {
    const done = rows.filter((row) => row.status === 'completed');
    const bytes = done.reduce((sum, row) => sum + (row.file_size || 0), 0);
    summary.textContent = rows.length
      ? t('downloads.summary', {
          count: rows.length, done: done.length, size: formatBytes(bytes),
        })
      : '';
  }

  if (!rows.length) {
    const filtered = Boolean(state.search || state.statusFilter);
    body.replaceChildren(emptyState({
      iconName: filtered ? 'search' : 'download',
      title: t(filtered ? 'downloads.emptyFiltered.title' : 'downloads.empty.title'),
      message: t(filtered ? 'downloads.emptyFiltered.message' : 'downloads.empty.message'),
    }));
    return;
  }

  const visible = rows.slice(0, PAGE_SIZE);

  // `mount` filters nullish children; `replaceChildren(a, null)` would render
  // the literal text "null".
  mount(body,
    h('div.table-wrap', h('table', [
      h('thead', h('tr', [
        h('th', { style: { width: '38px' } }, ''),
        h('th', t('downloads.col.file')),
        h('th', t('downloads.col.task')),
        h('th', t('downloads.col.size')),
        h('th', t('downloads.col.status')),
        h('th', { style: { minWidth: '160px' } }, t('downloads.col.progress')),
        h('th.actions', ''),
      ])),
      h('tbody', visible.map(buildRow)),
    ])),
    rows.length > PAGE_SIZE
      ? h('div', {
          style: {
            padding: 'var(--s4)', textAlign: 'center', fontSize: '12px',
            color: 'var(--text-muted)', borderTop: '1px solid var(--border)',
          },
        }, t('downloads.truncated', { shown: PAGE_SIZE, total: rows.length }))
      : null);
}

function buildRow(item) {
  const isComplete = item.status === 'completed';
  const downloadable = isComplete && item.filename;

  return h('tr', { dataset: { downloadId: String(item.id) } }, [
    h('td', kindIcon(item.filename || item.url)),
    h('td', [
      h('div.cell-strong.truncate', { title: item.filename || '' },
        item.filename || t('downloads.unnamed')),
      h('a.cell-mono.truncate', {
        href: item.url, target: '_blank', rel: 'noopener noreferrer',
        title: item.url, style: { maxWidth: '320px' },
      }, item.url),
      item.error_msg
        ? h('div', {
            style: { fontSize: '11.5px', color: 'var(--danger)', marginTop: '2px' },
          }, item.error_msg)
        : null,
    ]),
    h('td', h('span.tag', item.task_name || `#${item.task_id}`)),
    h('td.num', formatBytes(item.file_size)),
    h('td', statusBadge(item.status)),
    h('td', [
      h('div', { dataset: { role: 'progress' } },
        progressBar({ value: item.progress, tone: isComplete ? 'success' : '' })),
      h('div.progress-meta', [
        h('span', { dataset: { role: 'progress-text' } }, progressLabel(item)),
        h('span', { dataset: { role: 'progress-extra' } }),
      ]),
    ]),
    h('td.actions', [
      downloadable
        ? h('a.btn.btn-sm.btn-primary', {
            href: api.files.url(item.filename),
            download: item.filename,
            title: t('action.save2pc'),
          }, [icon('download'), t('action.save2pc')])
        : null,
      downloadable
        ? h('a.btn.btn-sm.btn-ghost', {
            href: api.files.url(item.filename, { inline: true }),
            target: '_blank', rel: 'noopener noreferrer', title: t('action.preview'),
          }, icon('external'))
        : null,
      h('button.btn.btn-sm.btn-ghost', {
        type: 'button', title: t('action.copyUrl'), 'aria-label': t('action.copyUrl'),
        onclick: () => copyText(item.url),
      }, icon('copy')),
    ]),
  ]);
}

function progressLabel(item) {
  if (item.status === 'completed') return formatBytes(item.file_size);
  if (item.status === 'failed') return t('status.failed');
  if (item.downloaded) {
    return item.file_size
      ? `${formatBytes(item.downloaded)} / ${formatBytes(item.file_size)}`
      : formatBytes(item.downloaded);
  }
  return item.status === 'pending' ? t('downloads.queued') : '—';
}

/** Overlay live byte counts coming from the progress socket. */
function applyLiveProgress() {
  for (const item of filteredRows().slice(0, PAGE_SIZE)) {
    if (item.status === 'completed' || item.status === 'failed') continue;
    const row = $(`tr[data-download-id="${item.id}"]`);
    if (!row) continue;

    const live = getFileProgress(item.id);
    if (!live) continue;

    const fill = $('.progress-fill', row);
    const text = $('[data-role="progress-text"]', row);
    const extra = $('[data-role="progress-extra"]', row);

    if (live.total) {
      fill.parentElement.dataset.indeterminate = 'false';
      fill.style.width = `${Math.min(100, (live.downloaded / live.total) * 100)}%`;
      text.textContent = `${formatBytes(live.downloaded)} / ${formatBytes(live.total)}`;
      extra.textContent = formatPercent(live.downloaded / live.total);
    } else {
      // Unknown total (live streams): show bytes only, no fake percentage.
      fill.parentElement.dataset.indeterminate = 'true';
      text.textContent = formatBytes(live.downloaded);
      extra.textContent = '';
    }
  }
}

function exportCsv() {
  const rows = filteredRows();
  if (!rows.length) {
    toast(t('downloads.exportEmpty'), { type: 'warning' });
    return;
  }
  const header = ['task_id', 'task_name', 'filename', 'status', 'size_bytes', 'url', 'error'];
  const escape = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const csv = [
    header.join(','),
    ...rows.map((row) => [
      row.task_id, row.task_name, row.filename, row.status,
      row.file_size || 0, row.url, row.error_msg,
    ].map(escape).join(',')),
  ].join('\n');

  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `auto-get-py-downloads-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
  toast(t('downloads.exported', { n: rows.length }), { type: 'success' });
}

/** Called by the global shortcut handler. */
export function focusDownloadsSearch() {
  searchInput?.focus();
  searchInput?.select();
}
