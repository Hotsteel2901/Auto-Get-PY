/** Dashboard: at-a-glance stats, live task monitor, recent task table. */

import {
  $, codeBlock, confirmDialog, emptyState, formatBytes, formatCount, formatWhen, h,
  icon, kvRow, modal, progressBar, skeletonList, statTile, statusBadge, toast,
} from '../core.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { getTaskProgress, onLiveChange, pruneProgress } from '../live.js';
import { navigate, setNavCount } from '../router.js';

let unsubscribeLive = null;
let pollTimer = null;
let tasksById = new Map();

/** Status → the action buttons offered for it. */
const STATUS_ACTIONS = {
  running: [
    { key: 'pause', iconName: 'pause' },
    { key: 'stop', iconName: 'stop', danger: true },
  ],
  paused: [
    { key: 'resume', iconName: 'play', primary: true },
    { key: 'stop', iconName: 'stop', danger: true },
  ],
  failed: [{ key: 'retry', iconName: 'refresh', primary: true }],
  cancelled: [{ key: 'retry', iconName: 'refresh', primary: true }],
  pending: [{ key: 'start', iconName: 'play', primary: true }],
};

/** Action key → the API method that performs it. */
const ACTION_METHOD = {
  start: 'start', pause: 'pause', resume: 'resume',
  stop: 'cancel', retry: 'retry',
};

const ACTION_TOAST = {
  start: 'dashboard.action.startSent',
  pause: 'dashboard.action.pauseSent',
  resume: 'dashboard.action.resumeSent',
  stop: 'dashboard.action.stopSent',
  retry: 'dashboard.action.retrySent',
};

export const dashboardPage = {
  id: 'dashboard',
  titleKey: 'dashboard.title',
  subtitleKey: 'dashboard.subtitle',
  icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3h8v8H3zM13 3h8v5h-8zM13 12h8v9h-8zM3 15h8v6H3z"/></svg>',

  async mount(container) {
    container.append(
      h('div#stats.grid.grid-4', { style: { marginBottom: 'var(--s4)' } }, skeletonList(1)),
      h('div.card.flush', [
        h('div.card-head', [
          h('h2', t('dashboard.recent')),
          h('span.card-sub#recent-count'),
          h('span.spacer'),
          h('button.btn.btn-sm#refresh-btn', {
            type: 'button',
            onclick: () => refresh({ spinner: true }),
          }, [icon('refresh'), t('action.refresh')]),
        ]),
        h('div.table-wrap', h('table', [
          h('thead', h('tr', [
            h('th', t('dashboard.col.task')),
            h('th', t('dashboard.col.status')),
            h('th', { style: { minWidth: '170px' } }, t('dashboard.col.progress')),
            h('th', t('dashboard.col.assets')),
            h('th', t('dashboard.col.created')),
            h('th.actions', ''),
          ])),
          h('tbody#recent-rows'),
        ])),
      ]),
    );

    await refresh();
    unsubscribeLive = onLiveChange(applyLiveProgress);
    pollTimer = window.setInterval(() => refresh(), 15_000);

    return () => {
      unsubscribeLive?.();
      window.clearInterval(pollTimer);
      tasksById.clear();
    };
  },
};

async function refresh({ spinner = false } = {}) {
  const button = $('#refresh-btn');
  if (spinner && button) {
    button.disabled = true;
    button.replaceChildren(h('span.spinner'), t('action.refreshing'));
  }

  try {
    const [statsResult, listResult] = await Promise.all([
      api.tasks.stats(),
      api.tasks.list({ limit: 50 }),
    ]);
    renderStats(statsResult.stats || {});
    renderTasks(listResult.tasks || []);
  } catch (error) {
    const tbody = $('#recent-rows');
    if (tbody) {
      tbody.replaceChildren(h('tr', h('td', { colspan: '6' }, emptyState({
        iconName: 'alert',
        title: t('dashboard.error.title'),
        message: error.message,
      }))));
    }
    $('#stats')?.replaceChildren(emptyState({
      iconName: 'alert',
      title: t('dashboard.error.offline'),
      message: t('dashboard.error.offlineMessage'),
    }));
    if (spinner) toast(error.message, { type: 'error' });
  } finally {
    if (button) {
      button.disabled = false;
      button.replaceChildren(icon('refresh'), t('action.refresh'));
    }
  }
}

function renderStats(stats) {
  const active = (stats.running || 0) + (stats.paused || 0);
  const tiles = [
    {
      label: t('dashboard.tile.running'), value: active, iconName: 'zap',
      color: 'var(--accent)', soft: 'var(--accent-soft)',
      foot: t('dashboard.tile.runningFoot', { n: stats.pending || 0 }),
    },
    {
      label: t('dashboard.tile.completed'), value: stats.completed || 0,
      iconName: 'check', color: 'var(--success)', soft: 'var(--success-soft)',
      foot: t('dashboard.tile.completedFoot'),
    },
    {
      label: t('dashboard.tile.failed'), value: stats.failed || 0,
      iconName: 'alert', color: 'var(--danger)', soft: 'var(--danger-soft)',
      foot: t('dashboard.tile.failedFoot'),
    },
    {
      label: t('dashboard.tile.total'), value: stats.all || 0,
      iconName: 'chart', color: 'var(--violet)', soft: 'var(--violet-soft)',
      foot: t('dashboard.tile.totalFoot'),
    },
  ];

  $('#stats')?.replaceChildren(...tiles.map((tile) =>
    statTile({ ...tile, value: formatCount(tile.value) })));

  setNavCount('dashboard', active);
}

function renderTasks(tasks) {
  tasksById = new Map(tasks.map((task) => [task.id, task]));
  pruneProgress(tasks.filter((task) => ['running', 'paused'].includes(task.status))
    .map((task) => task.id));

  const tbody = $('#recent-rows');
  if (!tbody) return;

  const countLabel = $('#recent-count');
  if (countLabel) {
    countLabel.textContent = tasks.length
      ? t('dashboard.recentShown', { n: tasks.length }) : '';
  }

  if (!tasks.length) {
    tbody.replaceChildren(h('tr', h('td', { colspan: '6' }, emptyState({
      iconName: 'zap',
      title: t('dashboard.empty.title'),
      message: t('dashboard.empty.message'),
      action: h('button.btn.btn-primary', {
        type: 'button',
        onclick: () => navigate('new-task'),
      }, [icon('plus'), t('dashboard.empty.action')]),
    }))));
    return;
  }

  tbody.replaceChildren(...tasks.map(buildRow));
  applyLiveProgress();
}

function buildRow(task) {
  const actions = (STATUS_ACTIONS[task.status] || []).map((action) => {
    const label = t(`action.${action.key}`);
    return h('button.btn.btn-sm', {
      type: 'button',
      class: action.danger ? 'btn-danger' : (action.primary ? 'btn-primary' : ''),
      title: label,
      onclick: () => runAction(task.id, action.key),
    }, [icon(action.iconName), label]);
  });

  return h('tr', { dataset: { taskId: String(task.id) } }, [
    h('td', [
      h('div.cell-strong', task.name || `#${task.id}`),
      h('a.cell-mono.truncate', {
        href: task.url, target: '_blank', rel: 'noopener noreferrer', title: task.url,
      }, task.url),
    ]),
    h('td', statusBadge(task.status)),
    h('td', [
      h('div', { dataset: { role: 'progress' } }, progressBar({ value: task.progress })),
      h('div.progress-meta', [
        h('span', { dataset: { role: 'progress-text' } },
          `${task.done_files || 0}/${task.total_files || 0}`),
        h('span.truncate', {
          dataset: { role: 'progress-extra' },
          style: { maxWidth: '160px' },
          title: task.error_msg || '',
        }, task.error_msg || ''),
      ]),
    ]),
    h('td.num', formatCount(task.total_media_found ?? task.total_files ?? 0)),
    h('td', { style: { color: 'var(--text-muted)', fontSize: '12px' } },
      formatWhen(task.created_at)),
    h('td.actions', h('div.btn-row', { style: { justifyContent: 'flex-end' } }, [
      ...actions,
      h('button.btn.btn-sm.btn-ghost', {
        type: 'button', title: t('action.details'), 'aria-label': t('action.details'),
        onclick: () => showDetails(task.id),
      }, icon('info')),
      h('button.btn.btn-sm.btn-ghost', {
        type: 'button', title: t('action.delete'), 'aria-label': t('action.delete'),
        onclick: () => removeTask(task),
      }, icon('trash')),
    ])),
  ]);
}

/** Overlay live socket progress on top of the last REST snapshot. */
function applyLiveProgress() {
  for (const id of tasksById.keys()) {
    const row = $(`tr[data-task-id="${id}"]`);
    if (!row) continue;

    const fill = $('.progress-fill', row);
    const text = $('[data-role="progress-text"]', row);
    const extra = $('[data-role="progress-extra"]', row);
    if (!fill || !text) continue;

    const live = getTaskProgress(id);
    if (live) {
      const pct = live.percent ?? (live.total ? (live.done / live.total) * 100 : 0);
      fill.style.width = `${Math.min(100, pct)}%`;
      text.textContent = `${live.done}/${live.total}`;
      const speed = live.speed ? `${live.speed.toFixed(1)}/s · ` : '';
      extra.textContent = live.currentFile ? `${speed}${live.currentFile}` : '';
      extra.title = live.currentFile || '';
    } else {
      const task = tasksById.get(id);
      const pct = task.total_files ? ((task.done_files || 0) / task.total_files) * 100 : 0;
      fill.style.width = `${Math.min(100, pct)}%`;
      text.textContent = `${task.done_files || 0}/${task.total_files || 0}`;
    }
  }
}

async function runAction(taskId, actionKey) {
  const method = ACTION_METHOD[actionKey] || actionKey;
  try {
    await api.tasks[method](taskId);
    toast(t(ACTION_TOAST[actionKey] || 'dashboard.action.failed'),
      { type: 'success', timeout: 1600 });
    await refresh();
  } catch (error) {
    toast(error.message, { type: 'error', title: t('dashboard.action.failed') });
  }
}

async function removeTask(task) {
  const ok = await confirmDialog({
    title: t('dashboard.delete.title'),
    message: t('dashboard.delete.message', {
      name: task.name || `#${task.id}`,
      n: task.total_files || 0,
    }),
    confirmLabel: t('dashboard.delete.confirm'),
    danger: true,
  });
  if (!ok) return;
  try {
    await api.tasks.remove(task.id);
    toast(t('dashboard.deleted'), { type: 'success' });
    await refresh();
  } catch (error) {
    toast(error.message, { type: 'error' });
  }
}

async function showDetails(taskId) {
  let payload;
  try {
    payload = await api.tasks.summary(taskId);
  } catch (error) {
    toast(error.message, { type: 'error' });
    return;
  }
  const { task, stats } = payload;
  const config = task.config_parsed || {};
  const extra = task.extra_info || {};

  modal({
    title: task.name || `#${task.id}`,
    width: 640,
    build: () => h('div', [
      h('div.kv-list', [
        kvRow(t('dashboard.details.status'), statusBadge(task.status)),
        kvRow(t('dashboard.details.target'), h('a.cell-mono', {
          href: task.url, target: '_blank', rel: 'noreferrer',
        }, task.url)),
        kvRow(t('dashboard.details.created'), formatWhen(task.created_at)),
        kvRow(t('dashboard.details.updated'), formatWhen(task.updated_at)),
        kvRow(t('dashboard.details.pages'), String(extra.pages_crawled ?? '—')),
        kvRow(t('dashboard.details.media'), String(extra.total_media_found ?? '—')),
        kvRow(t('dashboard.details.stylesheets'), String(extra.css_files_crawled ?? '—')),
        kvRow(t('dashboard.details.output'), h('span.mono', config.output_dir || './downloads')),
      ]),
      task.error_msg
        ? h('div.banner.banner-danger', { style: { marginTop: 'var(--s4)' } },
            [icon('alert'), h('div.banner-body', task.error_msg)])
        : null,
      h('h3', { style: { margin: 'var(--s6) 0 var(--s3)', fontSize: '13px' } },
        t('dashboard.details.breakdown')),
      h('div.grid.grid-4', [
        statTile({ label: t('dashboard.tile.completed'), value: stats.completed,
          iconName: 'check', color: 'var(--success)', soft: 'var(--success-soft)' }),
        statTile({ label: t('dashboard.tile.failed'), value: stats.failed,
          iconName: 'alert', color: 'var(--danger)', soft: 'var(--danger-soft)' }),
        statTile({ label: t('dashboard.details.pending'), value: stats.pending,
          iconName: 'clock', color: 'var(--warning)', soft: 'var(--warning-soft)' }),
        statTile({ label: t('dashboard.details.onDisk'), value: formatBytes(stats.bytes),
          iconName: 'archive', color: 'var(--accent)', soft: 'var(--accent-soft)' }),
      ]),
      h('h3', { style: { margin: 'var(--s6) 0 var(--s3)', fontSize: '13px' } },
        t('dashboard.details.config')),
      codeBlock(JSON.stringify(config, null, 2), { language: 'json' }),
    ]),
    actions: [
      {
        label: t('dashboard.details.openDownloads'),
        variant: 'btn-ghost',
        onClick: (close) => { close(); navigate('downloads'); },
      },
      { label: t('action.close'), variant: 'btn-primary' },
    ],
  });
}
