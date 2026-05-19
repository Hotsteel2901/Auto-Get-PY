const Downloads = {
    _currentTaskId: null,

    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-downloads">
                <h2 style="font-size:20px;margin-bottom:20px;">Downloads</h2>
                <div class="card">
                    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                        <div class="form-group" style="margin:0;min-width:200px;">
                            <select id="dl-task-filter" onchange="Downloads.loadTable()">
                                <option value="">All Tasks</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin:0;flex:1;min-width:200px;">
                            <input id="dl-search" placeholder="Search filename..." oninput="Downloads.loadTable()">
                        </div>
                    </div>
                </div>
                <div class="card">
                    <table><thead><tr><th>Filename</th><th>Size</th><th>Status</th><th>Progress</th><th>Time</th><th></th></tr></thead>
                    <tbody id="dl-table-body"></tbody></table>
                    <div id="dl-empty" style="text-align:center;padding:40px;color:var(--text-muted);display:none;">No downloads yet</div>
                </div>
            </div>`;

        await this.loadTasks();
        await this.loadTable();
    },

    async loadTasks() {
        try {
            const data = await API.tasks.list();
            const sel = document.getElementById('dl-task-filter');
            sel.innerHTML = '<option value="">All Tasks</option>' +
                data.tasks.map(t => `<option value="${t.id}">#${t.id} - ${escHtml(t.name)}</option>`).join('');
            if (this._currentTaskId) sel.value = this._currentTaskId;
        } catch (e) { console.error(e); }
    },

    async loadTable() {
        const taskId = document.getElementById('dl-task-filter').value;
        this._currentTaskId = taskId;
        const search = (document.getElementById('dl-search').value || '').toLowerCase();
        let downloads = [];

        try {
            if (taskId) {
                const d = await API.tasks.downloads(parseInt(taskId));
                downloads = d.downloads || [];
            } else {
                const data = await API.tasks.list();
                for (const t of (data.tasks || [])) {
                    const d = await API.tasks.downloads(t.id);
                    downloads.push(...(d.downloads || []).map(dl => ({ ...dl, task_name: t.name })));
                }
            }

            if (search) {
                downloads = downloads.filter(d => (d.filename || '').toLowerCase().includes(search));
            }

            const tbody = document.getElementById('dl-table-body');
            const empty = document.getElementById('dl-empty');

            if (downloads.length === 0) {
                tbody.innerHTML = '';
                empty.style.display = 'block';
            } else {
                empty.style.display = 'none';
                tbody.innerHTML = downloads.map(d => `
                    <tr>
                        <td>${escHtml(d.filename || d.url)}</td>
                        <td>${formatSize(d.file_size)}</td>
                        <td>${statusBadge(d.status)}</td>
                        <td>
                            <div class="progress-bar"><div class="progress-fill" style="width:${d.file_size ? (d.downloaded / d.file_size * 100) : 0}%"></div></div>
                            <small>${d.status === 'completed' ? 'Done' : formatSize(d.downloaded) + (d.file_size ? ' / ' + formatSize(d.file_size) : '')}</small>
                        </td>
                        <td style="font-size:12px;color:var(--text-muted);">${d.created_at || ''}</td>
                        <td>
                            ${d.status === 'completed' ? `<a href="${API.files.downloadUrl(d.filename)}" class="btn btn-sm btn-primary">Download</a>` : ''}
                            ${d.status === 'failed' ? `<button class="btn btn-sm btn-danger">${d.error_msg || 'Failed'}</button>` : ''}
                        </td>
                    </tr>`).join('');
            }
        } catch (e) {
            console.error(e);
            document.getElementById('dl-table-body').innerHTML = '<tr><td colspan="6" style="color:var(--danger);text-align:center;">Error loading downloads</td></tr>';
        }
    },
};
