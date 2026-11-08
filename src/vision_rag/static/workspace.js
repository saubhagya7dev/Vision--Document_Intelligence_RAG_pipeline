/* Persistent local workspace. API shapes mirror /openapi.json; untrusted text
   is always rendered through textContent/text nodes, never parsed as HTML. */
(() => {
    'use strict';
    /** @typedef {{evidence_id?:string, source:string, version_id:string, page:number, excerpt?:string}} Source */
    /** @typedef {{id:string, question:string, state:string, request:{document_ids:string[]|null}, result?:{answer:string,sources:Source[]}, error?:string}} Turn */
    const el = id => document.getElementById(id);
    let current = null, active = null, controller = null;
    let opening = false, creating = null, submitting = false, navigating = false, sourceTrigger = null;
    const terminal = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
    const status = text => { el('workspace-status').textContent = text; };
    const progress = (text, running = false) => {
        el('answer-progress').textContent = text;
        el('answer-progress').classList.toggle('luminous', running);
    };
    const working = () => Boolean(active || submitting || creating || opening || navigating);
    function saveDraft() {
        try { sessionStorage.setItem(`vr_draft_${current?.id || 'new'}`, el('chat-input').value); }
        catch { /* Storage full: the visible draft stays editable. */ }
    }
    function restoreDraft() {
        try { el('chat-input').value = sessionStorage.getItem(`vr_draft_${current?.id || 'new'}`) || ''; }
        catch { el('chat-input').value = ''; }
    }
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
    function report(error) { status(`Unable to complete: ${error.message}. Your draft and existing chats are kept.`); }
    function busy(value) {
        ['new-conversation', 'rename-conversation', 'delete-conversation', 'conversation-list', 'query-document-scope'].forEach(id => { el(id).disabled = value; });
        document.querySelectorAll('.recent-chat').forEach(b => { b.disabled = value; });
        el('stop-answer').hidden = !active;
        el('send-btn').hidden = Boolean(active);
        selection.updateSend();
    }
    function title() {
        el('conversation-title').textContent = current?.title || 'New conversation';
        el('rename-conversation').disabled = !current || working();
        el('delete-conversation').disabled = !current || working();
    }
    async function list() {
        const conversations = await api('/conversations');
        el('conversation-list').replaceChildren(new Option('Choose a conversation', ''));
        const recent = el('recent-conversations'); recent.replaceChildren();
        for (const c of conversations) {
            el('conversation-list').add(new Option(c.title, c.id));
            const b = button(c.title, () => {
                if (working() || selection.isLocked()) return;
                location.hash = '#chat'; openConversation(c.id).catch(report);
            }, 'recent-chat');
            if (c.id === current?.id) b.setAttribute('aria-current', 'page');
            b.disabled = working(); recent.append(b);
        }
        if (!conversations.length) {
            const p = document.createElement('p'); p.className = 'sidebar-empty'; p.textContent = 'Your chats will appear here.'; recent.append(p);
        }
        el('conversation-list').value = current?.id || ''; title();
        return conversations;
    }
    function scope() {
        const select = el('query-document-scope'); select.replaceChildren();
        for (const id of current?.document_ids || []) select.add(new Option(selection.name(id), id, true, true));
        selection.render(); title();
    }
    function scopeLabel(ids) {
        return ids === null ? 'All documents available when asked' : ids.length ? ids.map(selection.name).join(', ') : 'No documents selected';
    }
    async function setSelection(ids) {
        if (!current) await create();
        current = await api(`/conversations/${encode(current.id)}`, 'PATCH', {document_ids: ids});
        scope();
    }
    const selection = window.createDocumentSelection(api, () => current, setSelection, working, report);
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
    function atBottom() {
        const box = el('chat-messages'); return box.scrollHeight - box.scrollTop - box.clientHeight < 90;
    }
    function followLatest() {
        el('chat-messages').scrollTop = el('chat-messages').scrollHeight;
        el('jump-latest').hidden = true;
    }
    function render() {
        const messages = el('chat-messages'), follow = atBottom(), oldTop = messages.scrollTop;
        messages.replaceChildren(); title();
        if (!current?.messages.length) {
            const welcome = document.createElement('div'); welcome.className = 'welcome';
            welcome.innerHTML = '<p class="eyebrow">Your document workspace</p><h2>A clearer view<br>of your documents.</h2><p>Add a PDF or choose from your library to begin.</p>';
            const actions = document.createElement('div'); actions.className = 'welcome-actions';
            actions.append(button('↑ Upload PDF', () => el('attach-document').click(), 'btn btn-primary'),
                button('Choose from library ↗', () => selection.pick().catch(report), 'quiet-action'));
            const suggestions = document.createElement('div'); suggestions.className = 'suggestions';
            for (const [label, query] of [['Summarize this report', 'Summarize the main points in the selected report.'], ['Find a reported number', 'What revenue is reported, and for which period?']]) {
                suggestions.append(button(label, () => { el('chat-input').value = query; saveDraft(); el('chat-input').focus(); }, 'quiet-action'));
            }
            welcome.append(actions, suggestions); messages.append(welcome); return;
        }
        for (const turn of current.messages) {
            const article = document.createElement('article'); article.className = 'saved-turn';
            const question = document.createElement('div'); question.className = 'user-message';
            const q = document.createElement('h3'); q.textContent = turn.question;
            const label = document.createElement('p'); label.className = 'turn-scope'; label.textContent = scopeLabel(turn.request.document_ids);
            question.append(q, label); article.append(question);
            const brand = document.createElement('p'); brand.className = 'assistant-label'; brand.textContent = 'Vision'; article.append(brand);
            const answer = document.createElement('div'); answer.className = 'saved-answer'; answer.id = `answer-${turn.id}`;
            article.append(answer);
            if (turn.result) {
                const refs = turn.result.sources || [];
                richText(answer, turn.result.answer, refs);
                for (const source of refs) article.append(button(`${source.source} · Page ${source.page} ↗`, () => showEvidence(source), 'answer-source'));
                const actions = document.createElement('div'); actions.className = 'answer-actions';
                actions.append(button('Copy', async () => {
                    try { await navigator.clipboard.writeText(turn.result.answer); status('Answer copied.'); }
                    catch { status('Copy unavailable in this browser. Select the answer text to copy it.'); }
                }), button('Inspect evidence', () => {
                    sources(refs);
                    if (current.viewer?.version_id) showEvidence({version_id: current.viewer.version_id, page: current.viewer.page}, true);
                    else openEvidence();
                }));
                actions.append(button('Save finding', async () => {
                    try { await api(`/findings/from-message/${encode(turn.id)}`, 'POST', {}); status('Answer saved. Open Saved findings to review or export it.'); }
                    catch (error) { report(error); }
                }));
                article.append(actions);
            } else {
                answer.textContent = turn.error || (terminal.has(turn.state) ? `Answer ${turn.state}. You can retry this question.` : 'Preparing your answer…');
                if (!terminal.has(turn.state)) answer.classList.add('luminous');
                if (terminal.has(turn.state)) article.append(button('Retry question', () => ask(false, turn.question, turn.request), 'quiet-action'));
            }
            messages.append(article);
        }
        if (follow || submitting) followLatest(); else { messages.scrollTop = oldTop; el('jump-latest').hidden = false; }
    }
    function sources(items) {
        const list = el('source-list'); list.replaceChildren();
        if (!items.length) { list.textContent = 'No cited evidence for this answer.'; return; }
        for (const s of items) {
            const b = button(`${s.source} · page ${s.page}`, () => showEvidence(s), 'source-card');
            const image = document.createElement('img'); image.loading = 'lazy'; image.alt = '';
            image.src = `/api/v1/versions/${encode(s.version_id)}/pages/${s.page}?thumbnail=true`;
            b.prepend(image); list.append(b);
            if (s.excerpt) { const p = document.createElement('p'); p.textContent = s.excerpt; p.className = 'evidence-excerpt'; list.append(p); }
        }
    }
    function openEvidence() {
        sourceTrigger = document.activeElement;
        el('chat-evidence').hidden = false;
        document.querySelector('.workspace-layout').classList.add('has-evidence');
        el('close-evidence').focus();
    }
    function closeEvidence() {
        el('chat-evidence').hidden = true;
        document.querySelector('.workspace-layout').classList.remove('has-evidence');
        if (sourceTrigger?.isConnected) sourceTrigger.focus();
    }
    async function openConversation(id) {
        if (active || submitting || navigating || selection.isLocked()) return;
        navigating = true; busy(true);
        try {
            saveDraft(); evidence.reset(); closeEvidence();
            current = await api(`/conversations/${encode(id)}`);
            localStorage.setItem('vr_conversation', id);
            restoreDraft(); progress(''); scope(); render(); await list();
            sources(current.messages.filter(m => m.result).at(-1)?.result.sources || []);
            status(current.document_ids === null ? 'Choose documents for your next question. Earlier answers keep their original sources.' : 'Saved on this server.');
            const pending = current.messages.find(m => !terminal.has(m.state));
            if (pending) await watch(pending);
        } finally { navigating = false; busy(Boolean(active || submitting || opening)); title(); }
    }
    function create() {
        if (creating) return creating;
        creating = createConversation().finally(() => { creating = null; if (!active && !submitting) busy(false); title(); });
        return creating;
    }
    async function createConversation() {
        if (active) return;
        saveDraft(); busy(true); evidence.reset(); closeEvidence();
        const oldDraft = !current ? el('chat-input').value : '';
        current = await api('/conversations', 'POST', {title: 'New conversation', document_ids: []});
        el('chat-input').value = oldDraft; saveDraft(); progress('');
        localStorage.setItem('vr_conversation', current.id);
        scope(); render(); sources([]); await list(); status('Choose documents, then ask a question.');
        el('chat-input').focus();
    }
    async function open() {
        if (opening || active || creating || selection.isLocked()) return;
        opening = true; status('Loading saved conversations…');
        try {
            await selection.refresh();
            const conversations = await list();
            const id = current?.id || localStorage.getItem('vr_conversation');
            if (conversations.some(c => c.id === id)) await openConversation(id);
            else if (conversations.length) await openConversation(conversations[0].id);
            else { current = null; restoreDraft(); scope(); render(); status('Add a PDF or choose documents to begin.'); }
        } catch (error) { report(error); }
        finally { opening = false; busy(Boolean(active || submitting)); title(); }
    }
    async function ask(evidenceOnly = false, retryText = null, retryRequest = null) {
        if (working() || selection.isLocked()) return;
        const query = retryText || el('chat-input').value.trim(); if (!query) return;
        submitting = true; busy(true);
        try {
            if (retryRequest) {
                await setSelection(retryRequest.document_ids || []); evidenceOnly = retryRequest.evidence_only;
            }
            await selection.refresh();
            if (!selection.canSend()) { status('Choose ready documents before sending. Your question is kept.'); return; }
            progress('Submitting question…', true);
            if (!current) await create();
            const turn = await api(`/conversations/${encode(current.id)}/messages`, 'POST', {
                query, top_k: Math.max(3, current.document_ids?.length || 0), evidence_only: evidenceOnly || el('question-mode').value === 'pages',
            });
            if (current.title === 'New conversation') {
                current.title = query.slice(0, 100);
                // A cosmetic title failure must never abandon an accepted question.
                try { await api(`/conversations/${encode(current.id)}`, 'PATCH', {title: current.title}); }
                catch { status('Question accepted; the automatic chat title could not be saved.'); }
            }
            el('chat-input').value = ''; saveDraft(); current.messages.push(turn); render();
            try { await list(); } catch { /* The accepted question still needs its stream. */ }
            await watch(turn);
        } catch (error) { report(error); }
        finally { submitting = false; if (!active) { busy(false); el('answer-progress').classList.remove('luminous'); } }
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
                    if (type === 'progress') progress(({queued: 'Waiting to search…', retrieving: 'Searching selected documents…', generating: 'Writing answer…', validating: 'Checking page references…'})[data.stage] || 'Working on your question…', true);
                    if (type === 'answer-delta') {
                        if (data.reset) draft = ''; draft += data.text;
                        const follow = atBottom();
                        answer.textContent = draft; answer.classList.remove('luminous'); answer.classList.add('provisional');
                        progress('Writing answer · draft until page references are checked', true);
                        if (follow) followLatest(); else el('jump-latest').hidden = false;
                    }
                    if (type === 'final-answer' || type === 'error') {
                        finished = true;
                        progress(data.message || 'Answer saved. Inspect cited pages to check accuracy.');
                    }
                }
                if (chunk.done) break;
            }
            if (!finished) throw new Error('Connection ended before a final answer. Reopen the conversation to recover.');
        } catch (error) {
            if (error.name !== 'AbortError') report(error);
            try { await api(`/messages/${encode(turn.id)}/cancel`, 'POST', {}); } catch { /* Offline: server disconnect recovery handles this. */ }
            answer.textContent = 'Answer interrupted. Reopen this conversation to see its saved status and retry.';
            answer.classList.remove('provisional', 'luminous');
        } finally {
            active = null; controller = null; el('answer-progress').classList.remove('luminous'); busy(false);
            try {
                current = await api(`/conversations/${encode(current.id)}`); render();
                sources(current.messages.filter(m => m.result).at(-1)?.result.sources || []);
                const pending = current.messages.find(m => !terminal.has(m.state));
                if (pending) status('Cancellation requested; waiting for the current model/provider boundary. Reopen to refresh.');
            } catch (error) { report(error); }
        }
    }
    const evidence = window.createEvidenceViewer(api, () => current, report);
    const showEvidence = (source, restore = false) => { openEvidence(); return evidence.show(source, restore); };
    function setup() {
        evidence.setup(); selection.setup(); restoreDraft();
        el('chat-input').addEventListener('input', saveDraft);
        el('chat-input').addEventListener('keydown', event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); ask(); }
        });
        el('chat-messages').addEventListener('scroll', () => { el('jump-latest').hidden = atBottom(); });
        el('jump-latest').addEventListener('click', followLatest);
        el('close-evidence').addEventListener('click', closeEvidence);
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !el('chat-evidence').hidden && !document.querySelector('dialog[open]')) closeEvidence();
        });
        document.querySelector('.skip-link').addEventListener('click', event => { event.preventDefault(); el('app-main').focus(); });
        el('new-conversation').addEventListener('click', () => {
            if (working() || selection.isLocked()) return;
            location.hash = '#chat'; create().catch(report);
        });
        el('conversation-list').addEventListener('change', e => { if (e.target.value && !working()) openConversation(e.target.value).catch(report); });
        el('rename-conversation').addEventListener('click', async () => {
            if (!current || working()) return;
            const name = prompt('Conversation title', current.title)?.trim(); if (!name) return;
            try { current = await api(`/conversations/${encode(current.id)}`, 'PATCH', {title: name.slice(0, 160)}); await list(); }
            catch (error) { report(error); }
        });
        el('delete-conversation').addEventListener('click', async () => {
            if (!current || working() || selection.isLocked() || !confirm('Delete this chat and its messages? Documents and saved findings stay in the library.')) return;
            try {
                const id = current.id; await api(`/conversations/${encode(id)}`, 'DELETE');
                sessionStorage.removeItem(`vr_draft_${id}`); current = null;
                localStorage.removeItem('vr_conversation'); el('chat-input').value = ''; evidence.reset(); closeEvidence(); await open();
            } catch (error) { report(error); }
        });
        el('query-document-scope').addEventListener('change', e => selection.change([...e.target.selectedOptions].map(o => o.value)));
        el('question-form').addEventListener('submit', e => { e.preventDefault(); ask(); });
        el('find-pages-btn').addEventListener('click', () => ask(true));
        el('stop-answer').addEventListener('click', async () => {
            if (!active) return;
            try { await api(`/messages/${encode(active)}/cancel`, 'POST', {}); progress('Stopping at the next safe boundary…', true); }
            catch (error) { report(error); }
        });
        window.addEventListener('offline', () => status('Offline. Your draft is kept; reconnect to reopen saved chats.'));
        window.addEventListener('online', () => { if (!active) open(); });
        list().then(() => busy(false)).catch(report);
    }
    window.VisionWorkspace = {open, setup};
})();
