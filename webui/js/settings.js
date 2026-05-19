const Settings = {
    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-settings">
                <h2 style="font-size:20px;margin-bottom:20px;">Settings</h2>
                <div class="card">
                    <h3 class="section-title">Defaults</h3>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group"><label>Default Concurrency</label><input id="set-concurrency" type="number" value="5" min="1" max="20"></div>
                        <div class="form-group"><label>Default Output Directory</label><input id="set-output-dir" value="./downloads"></div>
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">AES Key Management</h3>
                    <div class="form-group"><label>AES Key (hex, 32 bytes)</label><input id="set-aes-key" placeholder="0123456789abcdef0123456789abcdef"></div>
                    <div class="form-group"><label>IV (hex, 16 bytes)</label><input id="set-aes-iv" placeholder="0123456789abcdef"></div>
                </div>
                <button class="btn btn-primary" onclick="Settings.save()">Save Settings</button>
            </div>`;

        try {
            const data = await API.settings.get();
            const s = data.settings || {};
            document.getElementById('set-concurrency').value = s.default_concurrency || '5';
            document.getElementById('set-output-dir').value = s.default_output_dir || './downloads';
            document.getElementById('set-aes-key').value = s.aes_key || '';
            document.getElementById('set-aes-iv').value = s.aes_iv || '';
        } catch (e) { console.error(e); }
    },

    async save() {
        try {
            await API.settings.update({
                default_concurrency: document.getElementById('set-concurrency').value,
                default_output_dir: document.getElementById('set-output-dir').value,
                aes_key: document.getElementById('set-aes-key').value,
                aes_iv: document.getElementById('set-aes-iv').value,
            });
            toast('Settings saved');
        } catch (e) { toast('Error: ' + e.message, 'error'); }
    },
};
