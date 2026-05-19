const API = {
    _base: '/api',

    async get(path) {
        const r = await fetch(this._base + path);
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    async post(path, body = {}) {
        const r = await fetch(this._base + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    async put(path, body = {}) {
        const r = await fetch(this._base + path, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    async del(path) {
        const r = await fetch(this._base + path, { method: 'DELETE' });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    tasks: {
        list: (status, offset = 0) => API.get(`/tasks?status=${status || ''}&offset=${offset}`),
        get: (id) => API.get(`/tasks/${id}`),
        create: (name, url, config) => API.post('/tasks', { name, url, config }),
        update: (id, data) => API.put(`/tasks/${id}`, data),
        delete: (id) => API.del(`/tasks/${id}`),
        start: (id) => API.post(`/tasks/${id}/start`),
        pause: (id) => API.post(`/tasks/${id}/pause`),
        resume: (id) => API.post(`/tasks/${id}/resume`),
        retry: (id) => API.post(`/tasks/${id}/retry`),
        downloads: (id, status) => API.get(`/tasks/${id}/downloads?status=${status || ''}`),
    },

    settings: {
        get: () => API.get('/settings'),
        update: (data) => API.put('/settings', data),
    },

    files: {
        list: (dir) => API.get(`/files?dir=${encodeURIComponent(dir || './downloads')}`),
        downloadUrl: (filename, dir) => `/api/files/download/${encodeURIComponent(filename)}?dir=${encodeURIComponent(dir || './downloads')}`,
    },
};
