const MEDIA_PRESETS = {
    images: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif', 'heic'],
    videos: ['mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'wmv', 'ts', 'm3u8'],
    audio: ['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus'],
    documents: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'epub'],
    archives: ['zip', 'rar', '7z', 'tar', 'gz'],
};

const DECRYPTORS = [
    { name: 'base64', label: 'Base64', hasConfig: false },
    { name: 'hex', label: 'Hex', hasConfig: false },
    { name: 'aes', label: 'AES', hasConfig: true },
    { name: 'xor', label: 'XOR', hasConfig: true },
    { name: 'url_sign', label: 'URL Sign Strip', hasConfig: false },
    { name: 'rot47', label: 'ROT47', hasConfig: false },
    { name: 'custom', label: 'Custom Expr', hasConfig: true },
];

const TaskForm = {
    render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-new-task">
                <h2 style="font-size:20px;margin-bottom:20px;">New Scraping Task</h2>
                <div class="card">
                    <div class="form-group"><label>Task Name</label><input id="task-name" placeholder="My scrape task"></div>
                    <div class="form-group"><label>Target URL</label><input id="task-url" placeholder="https://example.com/page/"></div>
                </div>
                <div class="card">
                    <h3 class="section-title">File Type Filters</h3>
                    ${Object.entries(MEDIA_PRESETS).map(([cat, exts]) => `
                        <div style="margin-bottom:12px;">
                            <strong style="font-size:12px;color:var(--text-muted);text-transform:uppercase;display:block;margin-bottom:6px;">${cat}</strong>
                            <div class="checkbox-group">${exts.map(ext => `
                                <label class="checkbox-chip checked" id="chip-${ext}">
                                    <input type="checkbox" checked data-ext="${ext}" onchange="TaskForm.toggleChip(this)">
                                    .${ext}
                                </label>`).join('')}</div>
                        </div>`).join('')}
                    <div class="form-group" style="margin-top:12px;">
                        <label>Custom Extensions (comma-separated)</label>
                        <input id="custom-exts" placeholder="dat, bin, tmp">
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">Decryptors</h3>
                    ${DECRYPTORS.map(d => `
                        <div style="margin-bottom:12px;">
                            <label class="checkbox-chip" id="dec-chip-${d.name}">
                                <input type="checkbox" data-dec="${d.name}" onchange="TaskForm.toggleDec(this)">
                                ${d.label}
                            </label>
                            ${d.hasConfig ? `<div id="dec-config-${d.name}" style="display:none;margin-top:8px;">${TaskForm.decConfigHTML(d.name)}</div>` : ''}
                        </div>`).join('')}
                </div>
                <div class="card">
                    <h3 class="section-title">Advanced Options</h3>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group"><label>Concurrency</label><input id="opt-concurrency" type="number" value="5" min="1" max="20"></div>
                        <div class="form-group"><label>Request Delay (s)</label><input id="opt-delay" type="number" value="0.5" step="0.1" min="0"></div>
                        <div class="form-group"><label>Timeout (s)</label><input id="opt-timeout" type="number" value="30"></div>
                        <div class="form-group"><label>Max Retries</label><input id="opt-retries" type="number" value="3" min="0"></div>
                        <div class="form-group"><label>Max File Size (MB)</label><input id="opt-max-size" type="number" value="500"></div>
                        <div class="form-group"><label>Output Directory</label><input id="opt-output-dir" value="./downloads"></div>
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">Custom Headers</h3>
                    <div class="kv-editor" id="headers-editor">
                        <div class="kv-row"><input placeholder="Header name" onchange="TaskForm.ensureHeaderRow()"><input placeholder="Value"></div>
                    </div>
                </div>
                <div style="margin-top:16px;">
                    <button class="btn btn-primary" onclick="TaskForm.submit()" style="padding:12px 32px;font-size:15px;">Start Scraping</button>
                </div>
            </div>`;
    },

    decConfigHTML(name) {
        if (name === 'aes') return `<div class="form-group"><label>AES Key (hex)</label><input id="dec-aes-key" placeholder="0123..."></div><div class="form-group"><label>IV (hex)</label><input id="dec-aes-iv" placeholder="0123..."></div><div class="form-group"><label>Mode</label><select id="dec-aes-mode"><option>CBC</option><option>ECB</option><option>GCM</option></select></div>`;
        if (name === 'xor') return `<div class="form-group"><label>XOR Key (hex)</label><input id="dec-xor-key" placeholder="55 or 0102..."></div>`;
        if (name === 'custom') return `<div class="form-group"><label>Python Expression</label><input id="dec-custom-expr" placeholder="bytes(b ^ 0xFF for b in content)"><small style="color:var(--text-muted);">Use <code>content</code> as the bytes variable</small></div>`;
        return '';
    },

    toggleChip(cb) { cb.parentElement.classList.toggle('checked', cb.checked); },
    toggleDec(cb) {
        cb.parentElement.classList.toggle('checked', cb.checked);
        const configDiv = document.getElementById(`dec-config-${cb.dataset.dec}`);
        if (configDiv) configDiv.style.display = cb.checked ? 'block' : 'none';
    },
    ensureHeaderRow() {
        const editor = document.getElementById('headers-editor');
        const rows = editor.querySelectorAll('.kv-row');
        const last = rows[rows.length - 1];
        if (last.querySelector('input').value || last.querySelectorAll('input')[1].value) {
            const row = document.createElement('div');
            row.className = 'kv-row';
            row.innerHTML = '<input placeholder="Header name" onchange="TaskForm.ensureHeaderRow()"><input placeholder="Value">';
            editor.appendChild(row);
        }
    },

    async submit() {
        const name = document.getElementById('task-name').value || 'Unnamed';
        const url = document.getElementById('task-url').value;
        if (!url) { toast('Please enter a URL', 'error'); return; }

        const include = [...document.querySelectorAll('[data-ext]:checked')].map(cb => `*.${cb.dataset.ext}`);
        const customExts = document.getElementById('custom-exts').value.split(',').map(s => s.trim()).filter(Boolean);
        customExts.forEach(e => include.push(`*.${e}`));

        const enabledDecs = [...document.querySelectorAll('[data-dec]:checked')].map(cb => cb.dataset.dec);
        const decOpts = {};
        if (enabledDecs.includes('aes')) {
            decOpts.aes = {
                key: document.getElementById('dec-aes-key')?.value || '',
                iv: document.getElementById('dec-aes-iv')?.value || '',
                mode: document.getElementById('dec-aes-mode')?.value || 'CBC',
            };
        }
        if (enabledDecs.includes('xor')) {
            decOpts.xor_key = document.getElementById('dec-xor-key')?.value || '';
        }
        if (enabledDecs.includes('custom')) {
            decOpts.custom_expr = document.getElementById('dec-custom-expr')?.value || '';
        }

        const headers = {};
        const rows = document.querySelectorAll('#headers-editor .kv-row');
        rows.forEach(row => {
            const inputs = row.querySelectorAll('input');
            if (inputs[0].value && inputs[1].value) headers[inputs[0].value] = inputs[1].value;
        });

        const config = {
            concurrency: parseInt(document.getElementById('opt-concurrency').value) || 5,
            output_dir: document.getElementById('opt-output-dir').value || './downloads',
            decryptors: enabledDecs,
            decryptor_opts: decOpts,
            url_filters: { include },
            custom_headers: headers,
            request_delay_sec: parseFloat(document.getElementById('opt-delay').value) || 0.5,
            request_timeout_sec: parseInt(document.getElementById('opt-timeout').value) || 30,
            max_retries: parseInt(document.getElementById('opt-retries').value) || 3,
            max_file_size_mb: parseInt(document.getElementById('opt-max-size').value) || 500,
        };

        try {
            const result = await API.tasks.create(name, url, config);
            await API.tasks.start(result.task.id);
            toast('Task started!');
            Router.navigate('dashboard');
        } catch (e) {
            toast('Error: ' + e.message, 'error');
        }
    },
};
