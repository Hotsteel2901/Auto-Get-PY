/**
 * Live update channel.
 *
 * Wraps the progress WebSocket with reconnect/backoff, a heartbeat, and a
 * subscribe/unsubscribe registry so pages can react to events without leaking
 * listeners when they unmount.
 */

import { store } from './core.js';

const MAX_BACKOFF = 15_000;
const PING_INTERVAL = 20_000;

const listeners = new Set();
let socket = null;
let reconnectTimer = null;
let pingTimer = null;
let attempt = 0;
let state = 'idle';
let manualClose = false;

const stateListeners = new Set();

function setState(next) {
  if (state === next) return;
  state = next;
  stateListeners.forEach((fn) => {
    try { fn(next); } catch (error) { console.error('ws state listener failed', error); }
  });
}

export function onStateChange(fn) {
  stateListeners.add(fn);
  fn(state);
  return () => stateListeners.delete(fn);
}

export function getState() { return state; }

/** Subscribe to server events. Returns an unsubscribe function. */
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit(message) {
  for (const fn of [...listeners]) {
    try {
      fn(message);
    } catch (error) {
      console.error('ws listener failed', error);
    }
  }
}

function socketUrl() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = store.get('token', '');
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${protocol}//${location.host}/ws/progress${query}`;
}

export function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  manualClose = false;
  setState(attempt === 0 ? 'connecting' : 'reconnecting');

  try {
    socket = new WebSocket(socketUrl());
  } catch (error) {
    console.error('websocket construction failed', error);
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    attempt = 0;
    setState('open');
    window.clearInterval(pingTimer);
    pingTimer = window.setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'ping' }));
      }
    }, PING_INTERVAL);
  };

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.type === 'heartbeat' || message.type === 'pong') return;
    if (message.type === 'hello' || message.type === 'subscribed') {
      emit({ type: 'connected', runningTasks: message.running_tasks || [] });
      return;
    }
    emit(message);
  };

  socket.onclose = () => {
    window.clearInterval(pingTimer);
    if (!manualClose) {
      setState('closed');
      scheduleReconnect();
    } else {
      setState('idle');
    }
  };

  socket.onerror = () => {
    // `onclose` always follows, so reconnection is handled in one place.
  };
}

function scheduleReconnect() {
  window.clearTimeout(reconnectTimer);
  const base = Math.min(MAX_BACKOFF, 800 * 2 ** Math.min(attempt, 4));
  const jitter = Math.random() * 400;
  attempt += 1;
  reconnectTimer = window.setTimeout(() => {
    setState('reconnecting');
    connect();
  }, base + jitter);
}

export function disconnect() {
  manualClose = true;
  window.clearTimeout(reconnectTimer);
  window.clearInterval(pingTimer);
  socket?.close();
  socket = null;
  setState('idle');
}

/** Force an immediate reconnect (used by the sidebar status button). */
export function reconnectNow() {
  window.clearTimeout(reconnectTimer);
  attempt = 0;
  if (socket && socket.readyState === WebSocket.OPEN) {
    // Already healthy: just confirm the state.
    setState('open');
    return;
  }
  socket?.close();
  socket = null;
  connect();
}

/** Reconnect when the tab becomes visible again after being backgrounded. */
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && state !== 'open') reconnectNow();
});

window.addEventListener('online', () => reconnectNow());
