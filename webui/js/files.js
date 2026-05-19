const Files = {
    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-files">
                <h2 style="font-size:20px;margin-bottom:20px;">Downloaded Files</h2>
                <div class="card">
                    <table><thead><tr><th>Filename</th><th>Size</th><th>Path</th><th></th></tr></thead>
                    <tbody id="files-table"></tbody></table>
                    <div id="files-empty" style="text-align:center;padding:40px;color:var(--text-muted);display:none;">No files downloaded yet</div>
                </div>
            </div>`;

        try {
            const data = await API.files.list('./downloads');
            const files = data.files || [];
            if (files.length === 0) {
                document.getElementById('files-empty').style.display = 'block';
            } else {
                document.getElementById('files-table').innerHTML = files.map(f => `
                    <tr>
                        <td>${escHtml(f.name)}</td>
                        <td>${formatSize(f.size)}</td>
                        <td style="font-size:12px;color:var(--text-muted);max-width:300px;overflow:hidden;text-overflow:ellipsis;">${escHtml(f.path)}</td>
                        <td><a href="${API.files.downloadUrl(f.path)}" class="btn btn-sm btn-primary">Download</a></td>
                    </tr>`).join('');
            }
        } catch (e) {
            console.error(e);
            toast('Error loading files', 'error');
        }
    },
};
