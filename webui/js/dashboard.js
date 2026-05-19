const Dashboard = {
    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-dashboard">
                <h2 style="font-size:20px;margin-bottom:20px;">Dashboard</h2>
                <div class="stat-cards" id="stat-cards"></div>
                <div id="active-tasks-section"></div>
                <div class="card"><h3 class="section-title">Recent Tasks</h3>
                    <table><thead><tr><th>Name</th><th>URL</th><th>Status</th><th>Progress</th><th>Created</th><th></th></tr></thead>
                    <tbody id="recent-tasks"></tbody></table>
                </div>
            </div>`;

        await this.loadStats();
        this.listenProgress();
    },

    async loadStats() {
        try {
            const data = await API.tasks.list('', 0);
            const tasks = data.tasks || [];
            const running = tasks.filter(t => t.status === 'running').length;
            const completed = tasks.filter(t => t.status === 'completed').length;
            const failed = tasks.filter(t => t.status === 'failed').length;

            document.getElementById('stat-cards').innerHTML = `
                <div class="stat-card"><div class="stat-value running">${running}</div><div class="stat-label">Running</div></div>
                <div class="stat-card"><div class="stat-value completed">${completed}</div><div class="stat-label">Completed</div></div>
                <div class="stat-card"><div class="stat-value failed">${failed}</div><div class="stat-label">Failed</div></div>
                <div class="stat-card"><div class="stat-value">${tasks.length}</div><div class="stat-label">Total</div></div>`;

            document.getElementById('recent-tasks').innerHTML = tasks.slice(0, 20).map(t => `
                <tr>
                    <td><strong>${escHtml(t.name)}</strong></td>
                    <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(t.url)}</td>
                    <td>${statusBadge(t.status)}</td>
                    <td>
                        <div class="progress-bar"><div class="progress-fill" style="width:${t.total_files ? (t.done_files / t.total_files * 100) : 0}%"></div></div>
                        <small>${t.done_files || 0}/${t.total_files || 0}</small>
                    </td>
                    <td style="color:var(--text-muted);font-size:12px;">${t.created_at || ''}</td>
                    <td>
                        ${t.status === 'running' ? `<button class="btn btn-sm" onclick="Dashboard.pauseTask(${t.id})">Pause</button>` : ''}
                        ${t.status === 'paused' ? `<button class="btn btn-sm btn-primary" onclick="Dashboard.resumeTask(${t.id})">Resume</button>` : ''}
                        ${t.status === 'failed' ? `<button class="btn btn-sm btn-primary" onclick="Dashboard.retryTask(${t.id})">Retry</button>` : ''}
                    </td>
                </tr>`).join('') || '<tr><td colspan="6" style="color:var(--text-muted);text-align:center;">No tasks yet</td></tr>';
        } catch (e) {
            console.error('Dashboard load error:', e);
        }
    },

    listenProgress() {
        WS.onProgress((msg) => {
            this.loadStats();
        });
    },

    async pauseTask(id) { await API.tasks.pause(id); toast('Task paused'); this.loadStats(); },
    async resumeTask(id) { await API.tasks.resume(id); toast('Task resumed'); this.loadStats(); },
    async retryTask(id) { await API.tasks.retry(id); toast('Retrying...'); this.loadStats(); },
};

function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}
