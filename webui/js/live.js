/**
 * Live progress state.
 *
 * One WebSocket subscription feeds every page. Task and per-file progress are
 * kept in maps here, and pages subscribe to change notifications instead of
 * talking to the socket themselves.
 */

import { subscribe } from './ws.js';

const taskProgress = new Map(); // task_id -> { done, total, currentFile, speed, percent }
const fileProgress = new Map(); // download_id -> { downloaded, total, percent }
const taskStatuses = new Map(); // task_id -> status string

const listeners = new Set();
let notifyScheduled = false;
let snapshotDirty = true;
let snapshot = { tasks: {}, files: {} };

function scheduleNotify() {
  if (notifyScheduled) return;
  notifyScheduled = true;
  // Coalesce bursts of progress frames into one repaint per animation frame.
  window.requestAnimationFrame(() => {
    notifyScheduled = false;
    snapshotDirty = true;
    for (const fn of [...listeners]) {
      try { fn(snapshot); } catch (error) { console.error('live listener failed', error); }
    }
  });
}

export function onLiveChange(fn) {
  listeners.add(fn);
  fn(getSnapshot());
  return () => listeners.delete(fn);
}

export function getSnapshot() {
  if (snapshotDirty) {
    snapshot = {
      tasks: Object.fromEntries(taskProgress),
      files: Object.fromEntries(fileProgress),
      statuses: Object.fromEntries(taskStatuses),
    };
    snapshotDirty = false;
  }
  return snapshot;
}

export function getTaskProgress(taskId) {
  return taskProgress.get(Number(taskId)) || null;
}

export function getFileProgress(downloadId) {
  return fileProgress.get(Number(downloadId)) || null;
}

export function clearFileProgress(taskId = null) {
  if (taskId === null) {
    fileProgress.clear();
  } else {
    for (const [, entry] of fileProgress) {
      if (entry.taskId === Number(taskId)) fileProgress.delete(entry.downloadId);
    }
  }
  scheduleNotify();
}

let started = false;

export function startLiveSync() {
  if (started) return;
  started = true;

  subscribe((message) => {
    switch (message.type) {
      case 'progress': {
        const id = Number(message.task_id);
        taskProgress.set(id, {
          done: message.done ?? 0,
          total: message.total ?? 0,
          currentFile: message.current_file || '',
          speed: message.speed || 0,
          percent: message.percent ?? 0,
          at: Date.now(),
        });
        scheduleNotify();
        break;
      }
      case 'file_progress': {
        const id = Number(message.download_id);
        fileProgress.set(id, {
          downloadId: id,
          taskId: Number(message.task_id),
          downloaded: message.downloaded ?? 0,
          total: message.total ?? null,
          percent: message.percent ?? null,
          at: Date.now(),
        });
        scheduleNotify();
        break;
      }
      case 'task_status': {
        taskStatuses.set(Number(message.task_id), message.status);
        if (['completed', 'failed', 'cancelled'].includes(message.status)) {
          clearFileProgress(Number(message.task_id));
        }
        scheduleNotify();
        break;
      }
      default:
        break;
    }
  });
}

/** Drop staged progress once the server confirms a fresh list. */
export function pruneProgress(activeTaskIds) {
  const keep = new Set(activeTaskIds.map(Number));
  let changed = false;
  for (const id of taskProgress.keys()) {
    if (!keep.has(id)) { taskProgress.delete(id); changed = true; }
  }
  if (changed) scheduleNotify();
}
