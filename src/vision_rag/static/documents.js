/* Explicit source selection and truthful preparation state. No automatic retries. */
window.createDocumentSelection = function(api, getCurrent, setSelection, isBusy, report) {
    'use strict';
    const el = id => document.getElementById(id);
    let data = {documents: [], search_enabled: true, index: null};
    let refreshing = null, pickerSelection = new Set(), upload = null, uploadConversation = null, uploading = false;
    let locked = false, unavailable = true;
    const ids = () => getCurrent()?.document_ids || [];
    const documentFor = id => data.documents.find(d => d.id === id);
    const name = id => documentFor(id)?.filename || 'Unavailable document';
    const ready = id => !unavailable && documentFor(id)?.search_state === 'ready';
    function text(tag, value, className) {
        const node = document.createElement(tag); node.textContent = value;
        if (className) node.className = className; return node;
    }
    function action(label, fn) {
        const b = text('button', label, 'quiet-action'); b.type = 'button';
        b.addEventListener('click', fn); return b;
    }
    function pendingLabel(doc) {
        if (unavailable) return 'Status unavailable. Reconnect to check readiness.';
        if (!data.search_enabled) return 'Scoped search is disabled. Enable PHASE4_ENABLED in server configuration.';
        if (!doc) return 'Document unavailable. Change your selection.';
        if (doc.search_state === 'failed') return 'Document preparation stopped. Your PDF remains saved.';
        if (doc.search_state === 'empty') return 'No searchable pages. Review page processing in details.';
        if (doc.search_state === 'reading') return 'Reading pages…';
        if (data.index?.state === 'failed') return 'Search preparation failed. Your PDF remains saved.';
        if (data.index?.state === 'cancelled') return 'Search preparation was cancelled.';
        return 'Preparing search…';
    }
    function render() {
        const selected = ids();
        el('library-count').textContent = unavailable ? '…' : String(data.documents.length).padStart(2, '0');
        el('selected-summary').textContent = selected.length
            ? `Using ${selected.length} document${selected.length === 1 ? '' : 's'} · ${selected.map(name).join(', ')}`
            : 'Choose documents to begin';
        el('choose-documents').textContent = selected.length ? 'Change' : 'Choose documents';
        const chips = el('composer-documents'); chips.replaceChildren();
        for (const id of selected) {
            const chip = text('div', '', 'document-chip');
            chip.append(text('span', `${name(id)} · ${ready(id) ? 'Ready' : 'Not ready'}`));
            const remove = action('×', () => change(selected.filter(key => key !== id)));
            remove.setAttribute('aria-label', `Remove ${name(id)} from this chat`);
            remove.disabled = locked || isBusy() || uploading; chip.append(remove); chips.append(chip);
        }
        const container = el('chat-preparation'); container.replaceChildren();
        if (upload && (uploading || uploadConversation === (getCurrent()?.id || null))) container.append(text('div', upload, 'preparation-row'));
        for (const id of selected.filter(id => !ready(id))) {
            const doc = documentFor(id), row = text('div', '', 'preparation-row');
            row.append(text('header', name(id)));
            const active = !unavailable && data.search_enabled && doc &&
                ['reading', 'preparing'].includes(doc.search_state) &&
                !['failed', 'cancelled'].includes(data.index?.state);
            row.append(text('p', pendingLabel(doc), active ? 'luminous' : ''));
            if (doc?.search_state === 'reading' && doc.total_pages) row.append(text('p', `${doc.pages_done} of ${doc.total_pages} pages processed`));
            const controls = text('div', '', 'preparation-actions');
            const details = text('a', 'View details ↗', 'quiet-action'); details.href = '#upload'; controls.append(details);
            if (doc && ['failed', 'cancelled'].includes(doc.state) && doc.job_id) {
                controls.append(action('Retry preparation', async () => {
                    try { await api(`/jobs/${encodeURIComponent(doc.job_id)}/retry`, 'POST', {}); await refresh(); }
                    catch (error) { report(error); }
                }));
            } else if (data.search_enabled && doc?.state === 'ready' && ['failed', 'cancelled'].includes(data.index?.state)) {
                controls.append(action('Retry search preparation', async () => {
                    try { await api('/indexes', 'POST', {activate_when_ready: true}); await refresh(); }
                    catch (error) { report(error); }
                }));
            }
            row.append(controls); container.append(row);
        }
        updateSend();
    }
    function updateSend() {
        const selected = ids(), waiting = selected.some(id => !ready(id));
        const disabled = locked || isBusy() || uploading || !selected.length || waiting;
        el('send-btn').disabled = disabled;
        el('find-pages-btn').disabled = disabled;
        el('choose-documents').disabled = locked || isBusy() || uploading;
        el('attach-document').disabled = locked || isBusy() || uploading || selected.length >= 6;
        el('send-readiness').textContent = uploading ? 'Uploading PDF' : !selected.length
            ? 'Choose documents' : waiting ? 'Waiting for documents' : '';
    }
    async function change(selected) {
        if (locked || isBusy() || uploading) return false;
        locked = true; updateSend();
        try { await setSelection(selected); render(); return true; }
        catch (error) {
            report(error); el('document-picker-status').textContent = `Selection not saved: ${error.message}`;
            return false;
        }
        finally { locked = false; render(); }
    }
    function refresh() {
        if (refreshing) return refreshing;
        refreshing = (async () => {
            try { data = await api('/workspace/readiness'); unavailable = false; }
            catch { unavailable = true; }
            finally { refreshing = null; render(); }
        })();
        return refreshing;
    }
    function options() {
        const list = el('document-options'); list.replaceChildren();
        const search = el('document-search').value.trim().toLocaleLowerCase();
        for (const doc of data.documents.filter(d => d.filename.toLocaleLowerCase().includes(search))) {
            const label = text('label', '', 'document-option'), check = document.createElement('input');
            check.type = 'checkbox'; check.value = doc.id; check.checked = pickerSelection.has(doc.id);
            check.addEventListener('change', () => {
                if (check.checked && pickerSelection.size >= 6) {
                    check.checked = false; el('document-picker-status').textContent = 'Choose up to six documents.'; return;
                }
                if (check.checked) pickerSelection.add(doc.id); else pickerSelection.delete(doc.id);
                el('document-picker-status').textContent = `${pickerSelection.size} selected`;
            });
            const description = text('span', doc.filename);
            description.append(text('small', `Version ${doc.version || '?'} · ${doc.page_count} pages · ${ready(doc.id) ? 'Ready to ask' : pendingLabel(doc)}`));
            label.append(check, description); list.append(label);
        }
        if (!list.children.length) list.append(text('p', unavailable ? 'Library unavailable. Reconnect and try again.' : 'No matching documents. Upload a PDF to get started.'));
    }
    async function pick() {
        if (isBusy() || locked || uploading) return;
        await refresh(); pickerSelection = new Set(ids());
        el('document-search').value = ''; el('document-picker-status').textContent = `${pickerSelection.size} selected`;
        options(); el('document-picker').showModal(); el('document-search').focus();
    }
    async function uploadFile(file) {
        if (uploading || locked || isBusy()) return;
        if (!file.name.toLowerCase().endsWith('.pdf')) { report(new Error('Choose a PDF file')); return; }
        if (ids().length >= 6) { report(new Error('Remove a selected document before adding another (six maximum)')); return; }
        uploading = true; uploadConversation = getCurrent()?.id || null; upload = `Uploading ${file.name}…`; render();
        let saved = false;
        try {
            const job = await window.VisionUploads.upload(file, percent => {
                upload = percent < 100 ? `Uploading ${file.name} · ${percent}%` : `Saving ${file.name}…`; render();
            });
            saved = true;
            const selected = [...new Set([...ids(), job.document_id])];
            await setSelection(selected);
            uploadConversation = getCurrent()?.id || null;
            upload = `${file.name} saved to your library and selected for this chat.`;
            await refresh();
        } catch (error) { upload = saved
            ? `${file.name} was saved, but could not be selected: ${error.message}. Choose it from your library.`
            : `Upload could not finish: ${error.message}. Your question draft is kept.`; }
        finally { uploading = false; render(); }
    }
    function setup() {
        el('choose-documents').addEventListener('click', () => pick().catch(report));
        el('close-document-picker').addEventListener('click', () => el('document-picker').close());
        el('document-search').addEventListener('input', options);
        el('select-ready-documents').addEventListener('click', () => {
            pickerSelection = new Set(data.documents.filter(d => ready(d.id)).slice(0, 6).map(d => d.id));
            options(); el('document-picker-status').textContent = `${pickerSelection.size} ready documents selected (six maximum)`;
        });
        el('apply-documents').addEventListener('click', async () => {
            const button = el('apply-documents'); button.disabled = true;
            try { if (await change([...pickerSelection])) el('document-picker').close(); }
            finally { button.disabled = false; }
        });
        el('attach-document').addEventListener('click', () => el('chat-file-input').click());
        el('chat-file-input').addEventListener('change', () => {
            const file = el('chat-file-input').files[0]; el('chat-file-input').value = '';
            if (file) uploadFile(file);
        });
        window.addEventListener('vision-library-changed', refresh);
        window.addEventListener('offline', () => { unavailable = true; render(); });
        setInterval(() => { if (!document.hidden && !el('page-chat').hidden && el('page-chat').classList.contains('active')) refresh(); }, 2500);
        render(); refresh();
    }
    return {setup, refresh, render, pick, change, name, ready, updateSend,
        canSend: () => !locked && !uploading && ids().length > 0 && ids().every(ready),
        isLocked: () => locked || uploading};
};
