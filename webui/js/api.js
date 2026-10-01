/**
 * REST client.
 *
 * Adds the auth token when the server requires one, applies a timeout to every
 * request, and turns error bodies into readable `ApiError` messages so the UI
 * never shows "[object Object]".
 */

import { store } from './core.js';
import { t } from './i18n.js';

const BASE = '/api';
const DEFAULT_TIMEOUT = 30_000;

export class ApiError extends Error {
  constructor(message, { status = 0, url = '', body = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.url = url;
    this.body = body;
  }
  get isOffline() { return this.status === 0; }
  get isAuth() { return this.status === 401; }
  get isMissing() { return this.status === 404; }
}

async function request(method, path, { body, timeout = DEFAULT_TIMEOUT, signal } = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(new Error('timeout')), timeout);
  if (signal) signal.addEventListener('abort', () => controller.abort(signal.reason), { once: true });

  const headers = { Accept: 'application/json' };
  const token = store.get('token', '');
  if (token) headers['X-API-Token'] = token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response;
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    window.clearTimeout(timer);
    if (error?.name === 'AbortError') {
      throw new ApiError(
        controller.signal.reason?.message === 'timeout'
          ? t('error.timeout', { n: Math.round(timeout / 1000) })
          : t('error.cancelled'),
        { url: path });
    }
    throw new ApiError(t('error.offline'), { url: path });
  }
  window.clearTimeout(timer);

  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = text; }
  }

  if (!response.ok) {
    throw new ApiError(describeError(response.status, payload), {
      status: response.status, url: path, body: payload,
    });
  }
  return payload;
}

function describeError(status, payload) {
  let detail = '';
  if (typeof payload === 'string') detail = payload;
  else if (payload && typeof payload === 'object') detail = payload.detail || payload.message || '';
  if (Array.isArray(detail)) {
    detail = detail.map((item) => item.msg || item.message || JSON.stringify(item)).join('; ');
  }
  if (status === 401) return t('error.unauthorized');
  if (status === 404) return detail || t('error.notFound');
  if (status === 409) return detail || t('error.conflict');
  if (status >= 500) return detail || t('error.server', { status });
  return detail || t('error.generic', { status });
}

const get = (path, options) => request('GET', path, options);
const post = (path, body, options) => request('POST', path, { body: body ?? {}, ...options });
const put = (path, body, options) => request('PUT', path, { body: body ?? {}, ...options });
const del = (path, options) => request('DELETE', path, options);

export const api = {
  health: () => get('/health', { timeout: 6000 }),
  system: () => get('/system'),

  tasks: {
    list: ({ status = '', limit = 100, offset = 0 } = {}) =>
      get(`/tasks?status=${encodeURIComponent(status)}&limit=${limit}&offset=${offset}`),
    stats: () => get('/tasks/stats'),
    get: (id) => get(`/tasks/${id}`),
    summary: (id) => get(`/tasks/${id}/summary`),
    create: (name, url, config) => post('/tasks', { name, url, config }),
    update: (id, patch) => put(`/tasks/${id}`, patch),
    remove: (id) => del(`/tasks/${id}`),
    start: (id) => post(`/tasks/${id}/start`),
    pause: (id) => post(`/tasks/${id}/pause`),
    resume: (id) => post(`/tasks/${id}/resume`),
    cancel: (id) => post(`/tasks/${id}/cancel`),
    retry: (id) => post(`/tasks/${id}/retry`),
  },

  downloads: {
    all: ({ status = '', limit = 500 } = {}) =>
      get(`/downloads?status=${encodeURIComponent(status)}&limit=${limit}`),
    forTask: (id, status = '') =>
      get(`/tasks/${id}/downloads?status=${encodeURIComponent(status)}`),
  },

  settings: {
    get: () => get('/settings'),
    save: (values) => put('/settings', values),
  },

  files: {
    list: ({ dir = '', sort = 'mtime', search = '' } = {}) => {
      const params = new URLSearchParams({ sort });
      if (dir) params.set('dir', dir);
      if (search) params.set('search', search);
      return get(`/files?${params}`);
    },
    remove: (path, dir = '') =>
      del(`/files/${encodeURI(path)}?dir=${encodeURIComponent(dir)}`),
    url: (path, { dir = '', inline = false } = {}) => {
      const params = new URLSearchParams();
      if (dir) params.set('dir', dir);
      if (inline) params.set('inline', 'true');
      const query = params.toString();
      return `${BASE}/files/download/${encodeURI(path)}${query ? `?${query}` : ''}`;
    },
  },

  agents: {
    manifest: () => get('/agent/manifest', { timeout: 8000 }),
    list: () => get('/agent/agents'),
    skill: (id) => get(`/agent/skill?agent=${encodeURIComponent(id)}&format=json`),
  },
};

/** Ping the server; resolves to a status string rather than throwing. */
export async function checkHealth() {
  try {
    const result = await api.health();
    return result?.status === 'ok';
  } catch {
    return false;
  }
}
