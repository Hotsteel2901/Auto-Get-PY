const MEDIA_PRESETS = {
    images: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif', 'heic'],
    videos: ['mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'wmv', 'ts', 'm3u8'],
    audio: ['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus'],
    documents: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'epub'],
    archives: ['zip', 'rar', '7z', 'tar', 'gz'],
    fonts: ['woff', 'woff2', 'ttf', 'otf', 'eot'],
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
                    <h3 class="section-title">🔥 Crawling Power</h3>
                    <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">Enable multiple discovery modes to find every media file on the target.</p>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group">
                            <label>Crawl Depth</label>
                            <input id="opt-crawl-depth" type="number" value="0" min="0" max="20" title="0=single page, 1+=follow links">
                            <small style="color:var(--text-muted);">0 = single page, higher = deeper</small>
                        </div>
                        <div class="form-group">
                            <label>Max Pages to Crawl</label>
                            <input id="opt-max-pages" type="number" value="500" min="1" max="100000">
                        </div>
                        <div class="form-group">
                            <label>Max Links per Page</label>
                            <input id="opt-max-links" type="number" value="20" min="1" max="200">
                        </div>
                        <div class="form-group">
                            <label>Allowed Path Prefixes</label>
                            <input id="opt-allowed-paths" placeholder="/gallery/, /blog/ (comma-separated)">
                        </div>
                    </div>
                    <div style="margin-top:12px;display:flex;gap:12px;flex-wrap:wrap;">
                        <label class="checkbox-chip checked" id="chip-follow-pagination">
                            <input type="checkbox" checked data-opt="follow-pagination" onchange="TaskForm.toggleChip(this)">
                            Auto Pagination
                        </label>
                        <label class="checkbox-chip" id="chip-follow-links">
                            <input type="checkbox" data-opt="follow-links" onchange="TaskForm.toggleChip(this)">
                            Follow Links
                        </label>
                        <label class="checkbox-chip" id="chip-site-discovery">
                            <input type="checkbox" data-opt="site-discovery" onchange="TaskForm.toggleChip(this)">
                            Site Discovery (sitemap + feeds)
                        </label>
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">🧠 Smart Extraction</h3>
                    <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">Advanced extraction for JS-heavy sites, CSS assets, iframes, and inline content.</p>
                    <div style="display:flex;gap:12px;flex-wrap:wrap;">
                        <label class="checkbox-chip" id="chip-use-browser">
                            <input type="checkbox" data-opt="use-browser" onchange="TaskForm.toggleChip(this)">
                            Browser Rendering (Playwright)
                        </label>
                        <label class="checkbox-chip checked" id="chip-crawl-css">
                            <input type="checkbox" checked data-opt="crawl-css" onchange="TaskForm.toggleChip(this)">
                            Crawl CSS Files
                        </label>
                        <label class="checkbox-chip checked" id="chip-crawl-iframes">
                            <input type="checkbox" checked data-opt="crawl-iframes" onchange="TaskForm.toggleChip(this)">
                            Crawl Iframes
                        </label>
                        <label class="checkbox-chip" id="chip-extract-base64">
                            <input type="checkbox" data-opt="extract-base64" onchange="TaskForm.toggleChip(this)">
                            Extract Base64 Images
                        </label>
                    </div>
                    <div id="browser-options" style="display:none;margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group">
                            <label>Max Scrolls</label>
                            <input id="opt-max-scrolls" type="number" value="30" min="1" max="200">
                        </div>
                        <div class="form-group">
                            <label>Scroll Delay (s)</label>
                            <input id="opt-scroll-delay" type="number" value="1.5" step="0.5" min="0.5">
                        </div>
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
                        <div class="form-group"><label>Concurrency</label><input id="opt-concurrency" type="number" value="5" min="1" max="50"></div>
                        <div class="form-group"><label>Request Delay (s)</label><input id="opt-delay" type="number" value="0.5" step="0.1" min="0"></div>
                        <div class="form-group"><label>Timeout (s)</label><input id="opt-timeout" type="number" value="30"></div>
                        <div class="form-group"><label>Max Retries</label><input id="opt-retries" type="number" value="3" min="0"></div>
                        <div class="form-group"><label>Max File Size (MB)</label><input id="opt-max-size" type="number" value="500"></div>
                        <div class="form-group"><label>Output Directory</label><input id="opt-output-dir" value="./downloads"></div>
                    </div>
                    <div class="form-group" style="margin-top:12px;">
                        <label>Proxy URL</label>
                        <input id="opt-proxy" placeholder="http://127.0.0.1:7890 or socks5://127.0.0.1:1080">
                        <small style="color:var(--text-muted);">HTTP/HTTPS/SOCKS5 proxy for all requests</small>
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">Custom Headers</h3>
                    <div class="kv-editor" id="headers-editor">
                        <div class="kv-row"><input placeholder="Header name" onchange="TaskForm.ensureHeaderRow()"><input placeholder="Value"></div>
                    </div>
                </div>
                <div style="margin-top:16px;">
                    <button class="btn btn-primary" onclick="TaskForm.submit()" style="padding:12px 32px;font-size:15px;">🚀 Start Scraping</button>
                </div>
            </div>`;

        // Wire up browser options visibility
        const browserCb = document.querySelector('[data-opt="use-browser"]');
        if (browserCb) {
            browserCb.addEventListener('change', () => {
                const opts = document.getElementById('browser-options');
                if (opts) opts.style.display = browserCb.checked ? 'grid' : 'none';
            });
        }
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

    _opt(name) {
        const el = document.querySelector(`[data-opt="${name}"]`);
        return el ? el.checked : false;
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

        const crawlDepth = parseInt(document.getElementById('opt-crawl-depth').value) || 0;
        const maxPages = parseInt(document.getElementById('opt-max-pages').value) || 500;
        const maxLinks = parseInt(document.getElementById('opt-max-links').value) || 20;
        const allowedPathsStr = document.getElementById('opt-allowed-paths')?.value || '';
        const allowedPaths = allowedPathsStr.split(',').map(s => s.trim()).filter(Boolean);
        const proxy = document.getElementById('opt-proxy')?.value?.trim() || null;

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
            // Crawling
            crawl_depth: crawlDepth,
            max_pages: maxPages,
            max_links_per_page: maxLinks,
            follow_pagination: this._opt('follow-pagination'),
            follow_links: this._opt('follow-links'),
            site_discovery: this._opt('site-discovery'),
            // Smart extraction
            use_browser: this._opt('use-browser'),
            crawl_css: this._opt('crawl-css'),
            crawl_iframes: this._opt('crawl-iframes'),
            extract_base64: this._opt('extract-base64'),
        };

        // Browser-specific options
        if (config.use_browser) {
            config.max_scrolls = parseInt(document.getElementById('opt-max-scrolls')?.value) || 30;
            config.scroll_delay = parseFloat(document.getElementById('opt-scroll-delay')?.value) || 1.5;
            config.scroll_page = true;
        }

        if (allowedPaths.length > 0) config.allowed_paths = allowedPaths;
        if (proxy) config.proxy = proxy;

        try {
            const result = await API.tasks.create(name, url, config);
            await API.tasks.start(result.task.id);
            toast('Task started! 🔥');
            Router.navigate('dashboard');
        } catch (e) {
            toast('Error: ' + e.message, 'error');
        }
    },
};
