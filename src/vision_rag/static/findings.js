/* Server-owned comparison findings. All document/provider text uses text nodes. */
(() => {
    'use strict';
    const el = id => document.getElementById(id);
    let current = null, working = false, opened = false;
    const encode = encodeURIComponent;
    const status = text => { el('finding-status').textContent = text; };
    const report = error => status(error.message);
    async function api(path, method = 'GET', body) {
        const response = await fetch('/api/v1' + path, {method,
            headers: {'Content-Type': 'application/json'},
            body: body === undefined ? undefined : JSON.stringify(body)});
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status})`);
        }
        return response.json();
    }
    const viewer = window.createEvidenceViewer(api, () => null, report, 'finding-');
    function text(tag, value, className) {
        const node = document.createElement(tag); node.textContent = value;
        if (className) node.className = className; return node;
    }
    function button(label, action) {
        const b = text('button', label, 'job-action'); b.type = 'button';
        b.addEventListener('click', action); return b;
    }
    function busy(value) {
        working = value;
        ['compare-submit', 'finding-list', 'save-finding', 'finding-reviewed', 'finding-title', 'delete-finding'].forEach(id => { el(id).disabled = value; });
    }
    async function list() {
        const records = await api('/findings');
        el('finding-list').replaceChildren(new Option('Choose a saved finding', ''));
        for (const item of records) el('finding-list').add(new Option(item.title, item.id));
        if (current?.state === 'saved') el('finding-list').value = current.id;
    }
    function citations(cell, refs, container) {
        for (const id of cell.citations || []) {
            const source = refs.find(s => s.evidence_id === id); if (!source) continue;
            const b = button(`[${refs.indexOf(source) + 1}] Page ${source.page}`, () => viewer.show(source));
            b.setAttribute('aria-label', `Inspect ${source.source}, version ${source.version_id.slice(0, 8)}, page ${source.page}`);
            container.append(b);
        }
    }
    function render() {
        const result = el('comparison-result'); result.replaceChildren();
        el('finding-actions').hidden = !current;
        el('finding-exports').replaceChildren();
        if (!current) { result.append(text('p', 'Compare reports or reopen a saved finding.')); return; }
        const content = current.content;
        el('finding-title').value = current.title;
        el('finding-reviewed').checked = current.reviewed;
        el('save-finding').textContent = current.state === 'saved' ? 'Save title' : 'Save finding';
        result.append(text('h2', current.title), text('p', content.answer || ''),
            text('p', `References: ${content.verification.references}. Semantic support: ${content.verification.semantic_support}. User marked reviewed: ${current.reviewed ? 'yes' : 'no'}.`, 'finding-verification'));
        if (content.table) {
            const table = document.createElement('table'), head = document.createElement('thead');
            table.append(text('caption', 'Reported values and context. No unit/currency conversion or inferred matching of periods/scopes.'));
            const row = document.createElement('tr'); row.append(text('th', 'Field'));
            for (const version of content.versions) {
                const th = text('th', `${version.filename} · v${version.ordinal} · ${version.id.slice(0, 8)}`);
                th.scope = 'col'; row.append(th);
            }
            head.append(row); table.append(head); const body = document.createElement('tbody');
            for (const field of content.fields) {
                const row = document.createElement('tr'), heading = text('th', field); heading.scope = 'row'; row.append(heading);
                for (const version of content.versions) {
                    const cell = content.table.cells.find(c => c.version_id === version.id && c.field === field);
                    const td = document.createElement('td'); td.dataset.status = cell.status;
                    td.append(text('strong', cell.status === 'missing' ? 'Not found in retrieved evidence' : cell.value), text('p', cell.status, 'turn-scope'));
                    if (cell.status !== 'missing') {
                        const dl = document.createElement('dl');
                        for (const key of ['unit', 'currency', 'period', 'scope']) {
                            dl.append(text('dt', key), text('dd', cell[key] === null ? 'Not stated' : cell[key]));
                        }
                        td.append(dl); citations(cell, content.sources, td);
                    }
                    row.append(td);
                }
                body.append(row);
            }
            table.append(body); result.append(table);
            for (const context of content.comparability || []) {
                if (context.different_reported_context.length) result.append(text('p',
                    `${context.field}: reported ${context.different_reported_context.join(', ')} differ. These values are not presented as a normalized comparison.`, 'job-error'));
                if (context.unstated_context.length) result.append(text('p',
                    `${context.field}: some ${context.unstated_context.join(', ')} context is unstated. Verify the evidence before interpreting differences.`, 'turn-scope'));
            }
            for (const item of content.retrieval || []) if (item.state === 'missing') {
                result.append(text('p', `${item.version_id.slice(0, 8)}: ${item.reason}. Rebuild while that version is active if it has no retained index.`, 'job-error'));
            }
        } else {
            result.append(text('p', content.answer || ''));
            for (const claim of content.claims || []) {
                const p = text('p', claim.text); citations(claim, content.sources, p); result.append(p);
            }
            for (const source of content.sources || []) result.append(button(
                `${source.source} · page ${source.page}`, () => viewer.show(source)));
        }
        result.append(text('p', `Content SHA256: ${current.content_hash}`, 'finding-hash'));
        if (current.state === 'saved') {
            for (const format of ['json', 'csv', 'md']) {
                const a = text('a', `Download ${format.toUpperCase()}`, 'job-action');
                a.href = `/api/v1/findings/${encode(current.id)}/export?format=${format}`;
                a.download = `finding-${current.id}.${format}`;
                a.addEventListener('click', async event => {
                    event.preventDefault();
                    try {
                        const response = await fetch(a.href);
                        if (!response.ok) {
                            const error = await response.json().catch(() => ({}));
                            throw new Error(error.detail || 'Export unavailable');
                        }
                        const url = URL.createObjectURL(await response.blob());
                        const download = document.createElement('a'); download.href = url; download.download = a.download;
                        document.body.append(download); download.click(); download.remove();
                        setTimeout(() => URL.revokeObjectURL(url), 1000);
                        status(`${format.toUpperCase()} export downloaded with source references.`);
                    } catch (error) { report(error); }
                });
                el('finding-exports').append(a);
            }
        }
    }
    async function load(id) {
        if (working) return;
        viewer.reset(); status('Opening saved finding…');
        try {
            current = await api(`/findings/${encode(id)}`); render();
            localStorage.setItem('vr_finding', id); status(`${current.state === 'saved' ? 'Saved finding' : 'Draft comparison'} ready. Inspect citations before marking reviewed.`);
        } catch (error) { current = null; render(); report(error); }
    }
    async function open() {
        if (working) return;
        status('Loading versions and saved findings…');
        try {
            const documents = await api('/documents');
            const select = el('comparison-versions'), selected = new Set([...select.selectedOptions].map(o => o.value));
            select.replaceChildren();
            for (const document of documents) {
                const versions = await api(`/documents/${encode(document.id)}/versions`);
                for (const version of versions.filter(v => v.state === 'ready')) {
                    select.add(new Option(`${version.filename} · v${version.ordinal} · ${version.id.slice(0, 8)}`, version.id, false, selected.has(version.id)));
                }
            }
            await list(); opened = true;
            const id = current?.id || localStorage.getItem('vr_finding');
            if (id) await load(id); else { render(); status('Select two to four ready versions and the fields to compare.'); }
        } catch (error) { report(error); }
    }
    async function compare(event) {
        event.preventDefault(); if (working) return;
        const versions = [...el('comparison-versions').selectedOptions].map(o => o.value);
        const fields = el('comparison-fields').value.split('\n').map(f => f.trim()).filter(Boolean);
        if (versions.length < 2 || versions.length > 4 || !fields.length || fields.length > 8) {
            status('Select two to four distinct versions and enter one to eight fields.'); return;
        }
        busy(true); status('Retrieving selected versions and building the comparison…');
        try {
            const finding = await api('/comparisons', 'POST', {
                question: el('comparison-question').value.trim(), version_ids: versions, fields});
            current = finding; viewer.reset(); render();
            localStorage.setItem('vr_finding', current.id);
            status('Draft comparison ready. Open cell citations, review reported context, then save.');
        } catch (error) { report(error); }
        finally { busy(false); }
    }
    async function save() {
        if (!current || working) return;
        const title = el('finding-title').value.trim(); if (!title) { status('Enter a title.'); return; }
        busy(true);
        try {
            current = await api(`/findings/${encode(current.id)}`, 'PATCH', {title});
            current = await api(`/findings/${encode(current.id)}/save`, 'POST', {});
            await list(); render(); status('Finding saved. Exports include source IDs, page links and verification status.');
        } catch (error) { report(error); }
        finally { busy(false); }
    }
    function setup() {
        viewer.setup();
        el('comparison-form').addEventListener('submit', compare);
        el('finding-list').addEventListener('change', e => { if (e.target.value) load(e.target.value); });
        el('refresh-findings').addEventListener('click', open);
        el('save-finding').addEventListener('click', save);
        el('finding-reviewed').addEventListener('change', async e => {
            if (!current || working) return;
            const reviewed = e.target.checked;
            const title = el('finding-title').value; busy(true);
            try { current = await api(`/findings/${encode(current.id)}`, 'PATCH', {reviewed}); render(); el('finding-title').value = title; status('User review status saved. Semantic support is still labeled unverified.'); }
            catch (error) { e.target.checked = !reviewed; report(error); }
            finally { busy(false); }
        });
        el('delete-finding').addEventListener('click', async () => {
            if (!current || working || !confirm('Delete this finding? Original documents remain in the library.')) return;
            try { await api(`/findings/${encode(current.id)}`, 'DELETE'); current = null; localStorage.removeItem('vr_finding'); viewer.reset(); await list(); render(); status('Finding deleted.'); }
            catch (error) { report(error); }
        });
        window.addEventListener('online', () => { if (opened && !working) open(); });
        window.addEventListener('offline', () => status('Offline. Reconnect to load, save or export server findings.'));
    }
    window.VisionFindings = {open, setup};
})();
