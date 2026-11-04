/* Persistent local workspace. API shapes mirror /openapi.json; untrusted text
   is always rendered through textContent/text nodes, never parsed as HTML. */
(() => {
    'use strict';
    /** @typedef {{evidence_id?:string, source:string, version_id:string, page:number, excerpt?:string}} Source */
    /** @typedef {{id:string, question:string, state:string, request:{document_ids:string[]|null}, result?:{answer:string,sources:Source[]}, error?:string}} Turn */
    const el = id => document.getElementById(id);
    let current = null, documents = [], active = null, controller = null;
    let opening = false, creating = null, submitting = false;
    const terminal = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
    const status = text => { el('workspace-status').textContent = text; };
    const encode = encodeURIComponent;
    async function api(path, method = 'GET', data) {
        const response = await fetch('/api/v1' + path, {
            method, headers: {'Content-Type': 'application/json'},
            body: data === undefined ? undefined : JSON.stringify(data),
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status})`);
        }
        return response.json();
    }
    function button(text, action, className = 'job-action') {
        const b = document.createElement('button'); b.type = 'button';
        b.className = className; b.textContent = text; b.addEventListener('click', action);
        return b;
    }
    function report(error) { status(`Unable to complete: ${error.message}. Your saved conversation remains available.`); }
    function busy(value) {
        ['send-btn', 'find-pages-btn', 'new-conversation', 'rename-conversation',
            'delete-conversation', 'conversation-list', 'query-document-scope'].forEach(id => { el(id).disabled = value; });
        el('stop-answer').hidden = !value || !active;
    }
    async function list() {
        const conversations = await api('/conversations');
        el('conversation-list').replaceChildren(new Option('Choose a conversation', ''));
        for (const c of conversations) el('conversation-list').add(new Option(c.title, c.id));
        el('conversation-list').value = current?.id || '';
        return conversations;
    }
    function scope() {
        const select = el('query-document-scope'); select.replaceChildren();
        const wanted = new Set(current?.document_ids || []);
        const known = new Set(documents.map(d => d.id));
        for (const d of documents) select.add(new Option(d.filename, d.id, false, wanted.has(d.id)));
        for (const id of wanted) if (!known.has(id)) select.add(new Option(`Unavailable document (${id.slice(0, 8)})`, id, false, true));
    }
    function scopeLabel(ids) {
        return ids === null ? 'All live documents (automatic scope)' : ids.length ? ids.map(id => documents.find(d => d.id === id)?.filename || `Unavailable document ${id.slice(0, 8)}`).join(', ') : 'No documents selected';
    }
    function richText(node, text, sources) {
        const tokens = /(\[E[a-f0-9]{16}\]|\*\*[^*]+\*\*|`[^`]+`)/g;
        for (const part of String(text || '').split(tokens)) {
            const source = sources.find(s => `[${s.evidence_id}]` === part);
            if (source) {
                const i = sources.indexOf(source) + 1;
                const b = button(`[${i}]`, () => showEvidence(source), 'citation-link');
                b.setAttribute('aria-label', `Open source ${i}: ${source.source}, page ${source.page}`); node.append(b);
            } else if (part.startsWith('**') && part.endsWith('**')) {
                const b = document.createElement('strong'); b.textContent = part.slice(2, -2); node.append(b);
            } else if (part.startsWith('`') && part.endsWith('`')) {
                const code = document.createElement('code'); code.textContent = part.slice(1, -1); node.append(code);
            } else node.append(document.createTextNode(part));
        }
    }
    function render() {
        const messages = el('chat-messages'); messages.replaceChildren();
        if (!current?.messages.length) {
            const p = document.createElement('p'); p.className = 'workspace-empty';
            p.textContent = 'Start a conversation, choose documents, then ask a question. Find pages searches locally without contacting the answer provider.';
            messages.append(p); return;
        }
        for (const turn of current.messages) {
            const article = document.createElement('article'); article.className = 'saved-turn';
            const q = document.createElement('h3'); q.textContent = turn.question;
            const label = document.createElement('p'); label.className = 'turn-scope';
            label.textContent = `Scope: ${scopeLabel(turn.request.document_ids)}`;
            article.append(q, label);
            const answer = document.createElement('div'); answer.className = 'saved-answer';
            answer.id = `answer-${turn.id}`;
            if (turn.result) {
                richText(answer, turn.result.answer, turn.result.sources || []);
                article.append(button('Inspect evidence', () => sources(turn.result.sources || [])));
            } else {
                answer.textContent = turn.error || (terminal.has(turn.state) ? turn.state : 'Waiting for an answer…');
                if (terminal.has(turn.state)) article.append(button('Retry question', () => ask(false, turn.question, turn.request)));
            }
            article.append(answer); messages.append(article);
        }
        messages.scrollTop = messages.scrollHeight;
    }
    function sources(items) {
        const list = el('source-list'); list.replaceChildren();
        if (!items.length) { list.textContent = 'No cited evidence for this answer.'; return; }
        for (const s of items) {
            const b = button(`${s.source} · page ${s.page}`, () => showEvidence(s), 'source-card');
            const image = document.createElement('img'); image.loading = 'lazy';
            image.alt = `Thumbnail: ${s.source}, page ${s.page}`;
            image.src = `/api/v1/versions/${encode(s.version_id)}/pages/${s.page}?thumbnail=true`;
            b.prepend(image); list.append(b);
            if (s.excerpt) { const p = document.createElement('p'); p.textContent = s.excerpt; p.className = 'evidence-excerpt'; list.append(p); }
        }
    }
    async function openConversation(id) {
        if (active) return;
        evidence.reset();
        current = await api(`/conversations/${encode(id)}`);
        localStorage.setItem('vr_conversation', id);
        scope(); render(); await list();
        sources(current.messages.filter(m => m.result).at(-1)?.result.sources || []);
        evidence.reset();
        if (current.viewer?.version_id) await showEvidence({version_id: current.viewer.version_id, page: current.viewer.page}, true);
        status('Conversation saved on this server.');
        const pending = current.messages.find(m => !terminal.has(m.state));
        if (pending) await watch(pending);
    }
    function create() {
        if (creating) return creating;
        creating = createConversation().finally(() => { creating = null; if (!active && !submitting) busy(false); });
        return creating;
    }
    async function createConversation() {
        if (active) return;
        busy(true);
        evidence.reset();
        current = await api('/conversations', 'POST', {title: 'New conversation', document_ids: null});
        el('answer-progress').textContent = '';
        localStorage.setItem('vr_conversation', current.id);
        scope(); render(); sources([]); evidence.reset();
        el('viewer-controls').hidden = true; await list(); status('New conversation ready.');
        el('chat-input').focus();
    }
    async function open() {
        if (opening || active) return;
        opening = true; status('Loading saved conversations…');
        try {
            documents = await api('/documents');
            const conversations = await list();
            const id = current?.id || localStorage.getItem('vr_conversation');
            if (conversations.some(c => c.id === id)) await openConversation(id);
            else if (conversations.length) await openConversation(conversations[0].id);
            else { current = null; scope(); render(); status('No saved conversations. Ask a question to create one.'); }
        } catch (error) { report(error); }
        finally { opening = false; }
    }
    async function ask(evidenceOnly = false, retryText = null, retryRequest = null) {
        if (active || submitting) return;
        const query = retryText || el('chat-input').value.trim(); if (!query) return;
        submitting = true; busy(true);
        el('answer-progress').textContent = 'Submitting question…';
        try {
            if (!current) await create();
            if (retryRequest) {
                // Retrying preserves the failed turn's document scope, including unavailable IDs.
                current = await api(`/conversations/${encode(current.id)}`, 'PATCH', {document_ids: retryRequest.document_ids});
                scope(); evidenceOnly = retryRequest.evidence_only;
            }
            const turn = await api(`/conversations/${encode(current.id)}/messages`, 'POST', {
                query, top_k: Math.max(3, current.document_ids?.length || 0), evidence_only: evidenceOnly,
            });
            if (current.title === 'New conversation') {
                current.title = query.slice(0, 100);
                await api(`/conversations/${encode(current.id)}`, 'PATCH', {title: current.title});
            }
            el('chat-input').value = ''; current.messages.push(turn); render(); await list(); await watch(turn);
        } catch (error) { report(error); }
        finally { submitting = false; if (!active) busy(false); }
    }
    async function watch(turn) {
        active = turn.id; busy(true); controller = new AbortController();
        let buffer = '', draft = '', finished = false;
        const answer = el(`answer-${turn.id}`);
        try {
            const response = await fetch(`/api/v1/messages/${encode(turn.id)}/events`, {signal: controller.signal});
            if (!response.ok || !response.body) throw new Error('Answer stream unavailable');
            const reader = response.body.getReader(), decoder = new TextDecoder();
            while (true) {
                const chunk = await reader.read();
                buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
                let boundary;
                while ((boundary = buffer.indexOf('\n\n')) >= 0) {
                    const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
                    const type = block.split('\n').find(l => l.startsWith('event: '))?.slice(7);
                    const dataLine = block.split('\n').find(l => l.startsWith('data: '));
                    if (!type || !dataLine) continue;
                    const data = JSON.parse(dataLine.slice(6));
                    if (type === 'progress') el('answer-progress').textContent = `${data.stage}${data.tier ? ` · ${data.tier}` : ''}…`;
                    if (type === 'answer-delta') {
                        if (data.reset) draft = ''; draft += data.text;
                        answer.textContent = draft; answer.classList.add('provisional');
                        el('answer-progress').textContent = 'Draft answer — checking references before publishing.';
                    }
                    if (type === 'final-answer' || type === 'error') {
                        finished = true;
                        el('answer-progress').textContent = data.message || 'Answer saved. Final references are authoritative.';
                    }
                }
                if (chunk.done) break;
            }
            if (!finished) throw new Error('Connection ended before a final answer. Reopen the conversation to recover.');
        } catch (error) {
            if (error.name !== 'AbortError') report(error);
            try { await api(`/messages/${encode(turn.id)}/cancel`, 'POST', {}); } catch { /* Offline: server disconnect recovery handles this. */ }
            answer.textContent = 'Answer interrupted. Reopen this conversation to see its saved status and retry.';
            answer.classList.remove('provisional');
        } finally {
            active = null; controller = null; busy(false);
            try {
                current = await api(`/conversations/${encode(current.id)}`); render();
                sources(current.messages.filter(m => m.result).at(-1)?.result.sources || []);
                const pending = current.messages.find(m => !terminal.has(m.state));
                if (pending) status('Cancellation requested; waiting for the current model/provider boundary. Reopen to refresh.');
            } catch (error) { report(error); }
        }
    }
    const evidence = window.createEvidenceViewer(api, () => current, report);
    const showEvidence = (source, restore = false) => evidence.show(source, restore);
    function setup() {
        evidence.setup();
        document.querySelector('.skip-link').addEventListener('click', event => {
            event.preventDefault(); el('app-main').focus();
        });
        el('new-conversation').addEventListener('click', () => create().catch(report));
        el('conversation-list').addEventListener('change', e => { if (e.target.value) openConversation(e.target.value).catch(report); });
        el('rename-conversation').addEventListener('click', async () => {
            if (!current) return;
            const title = prompt('Conversation title', current.title)?.trim(); if (!title) return;
            try { current = await api(`/conversations/${encode(current.id)}`, 'PATCH', {title: title.slice(0, 160)}); await list(); } catch (error) { report(error); }
        });
        el('delete-conversation').addEventListener('click', async () => {
            if (!current || !confirm('Delete this saved conversation and its messages? Documents stay in the library.')) return;
            try { await api(`/conversations/${encode(current.id)}`, 'DELETE'); current = null; localStorage.removeItem('vr_conversation'); await open(); } catch (error) { report(error); }
        });
        el('query-document-scope').addEventListener('change', async e => {
            const ids = [...e.target.selectedOptions].map(o => o.value);
            if (ids.length > 6) { status('Select at most six documents.'); scope(); return; }
            try { if (!current) await create(); current = await api(`/conversations/${encode(current.id)}`, 'PATCH', {document_ids: ids.length ? ids : null}); scope(); } catch (error) { report(error); }
        });
        el('question-form').addEventListener('submit', e => { e.preventDefault(); ask(); });
        el('find-pages-btn').addEventListener('click', () => ask(true));
        el('stop-answer').addEventListener('click', async () => {
            if (!active) return;
            try { await api(`/messages/${encode(active)}/cancel`, 'POST', {}); el('answer-progress').textContent = 'Cancellation requested…'; } catch (error) { report(error); }
        });
        window.addEventListener('offline', () => status('Offline. Saved server conversations will be available after reconnection.'));
        window.addEventListener('online', () => { if (!active) open(); });
    }
    window.VisionWorkspace = {open, setup};
})();
