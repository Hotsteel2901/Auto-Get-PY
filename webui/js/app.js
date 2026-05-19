const WS = {
    _ws: null,
    _callbacks: [],

    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this._ws = new WebSocket(`${proto}//${location.host}/ws/progress`);

        this._ws.onopen = () => {
            document.getElementById('ws-status').textContent = 'Connected';
            document.getElementById('ws-status').className = 'ws-status connected';
        };

        this._ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'progress') {
                this._callbacks.forEach(cb => cb(msg));
            }
        };

        this._ws.onclose = () => {
            document.getElementById('ws-status').textContent = 'Disconnected';
            document.getElementById('ws-status').className = 'ws-status disconnected';
            setTimeout(() => this.connect(), 3000);
        };

        this._ws.onerror = () => {};
    },

    onProgress(cb) { this._callbacks.push(cb); return () => { this._callbacks = this._callbacks.filter(c => c !== cb); }; },
};

const Router = {
    _current: null,

    navigate(page) {
        if (this._current === page) return;
        this._current = page;

        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        const link = document.querySelector(`[data-page="${page}"]`);
        if (link) link.classList.add('active');

        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const el = document.getElementById(`page-${page}`);
        if (el) el.classList.add('active');

        if (page === 'dashboard') Dashboard.render();
        else if (page === 'new-task') TaskForm.render();
        else if (page === 'downloads') Downloads.render();
        else if (page === 'settings') Settings.render();
        else if (page === 'files') Files.render();
    },
};

function toast(msg, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

function formatSize(bytes) {
    if (!bytes) return '-';
    const u = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < u.length - 1) { bytes /= 1024; i++; }
    return `${bytes.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function statusBadge(status) {
    return `<span class="badge badge-${status}">${status}</span>`;
}

document.addEventListener('DOMContentLoaded', () => {
    WS.connect();
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            Router.navigate(link.dataset.page);
        });
    });
    Router.navigate('dashboard');
});
