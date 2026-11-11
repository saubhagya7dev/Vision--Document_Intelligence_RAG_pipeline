/* A research desk built from persisted owner data, never illustrative metrics. */
(() => {
    'use strict';
    const el = id => document.getElementById(id);
    let loading = null, installed = false;
    const recent = records => [...(records || [])].sort((a, b) =>
        (Date.parse(b.updated_at || b.created_at) || 0) - (Date.parse(a.updated_at || a.created_at) || 0));
    function model({stats = null, readiness = null, conversations = null, findings = null} = {}) {
        const documents = readiness ? readiness.documents.map(doc => ({...doc,
            deskState: doc.search_state === 'ready' ? 'ready'
                : ['failed', 'cancelled', 'empty'].includes(doc.search_state)
                    || (!readiness.search_enabled)
                    || (doc.search_state === 'preparing' && ['failed', 'cancelled'].includes(readiness.index?.state))
                    ? 'attention' : 'preparing',
        })) : null;
        const ready = documents?.filter(d => d.deskState === 'ready') || [];
        const preparing = documents?.filter(d => d.deskState === 'preparing') || [];
        const attention = documents?.filter(d => d.deskState === 'attention') || [];
        const saved = findings ? recent(findings.filter(f => f.state === 'saved')) : null;
        return {stats, readiness, documents: documents ? recent(documents) : null,
            ready, preparing, attention, conversations: conversations ? recent(conversations) : null, saved};
    }
    function node(tag, value = '', className = '') {
        const n = document.createElement(tag); n.textContent = value; n.className = className; return n;
    }
    function link(label, href, className = '') { const n = node('a', label, className); n.href = href; return n; }
    function action(label, callback) {
        const n = node('button', label, 'desk-row-action'); n.type = 'button';
        n.addEventListener('click', async () => {
            n.disabled = true;
            try { await callback(); }
            catch { el('dashboard-status').textContent = 'Unable to open that item. Refresh your workspace and try again.'; }
            finally { n.disabled = false; }
        }); return n;
    }
    function empty(container, message, label, href) {
        const box = node('div', '', 'desk-empty'); box.append(node('p', message));
        if (label) box.append(link(label, href, 'desk-empty-action')); container.append(box);
    }
    function date(value) {
        const stamp = new Date(value);
        return Number.isNaN(stamp.getTime()) ? 'Saved on this server' : stamp.toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
    }
    function render(data) {
        el('desk-ready').textContent = data.documents ? data.ready.length : '—';
        el('desk-ready-note').textContent = data.documents ? `${data.ready.length} of ${data.documents.length} documents searchable` : 'Library unavailable';
        el('desk-preparing').textContent = data.documents ? data.preparing.length : '—';
        el('desk-preparing-note').textContent = data.documents ? `${data.attention.length} need attention` : 'Readiness unavailable';
        el('desk-answers').textContent = data.stats?.completed_queries ?? '—';
        el('desk-findings').textContent = data.saved ? data.saved.length : '—';
        const readiness = el('desk-readiness-content'); readiness.replaceChildren();
        if (!data.documents) empty(readiness, 'Readiness could not be loaded. Refresh to try again.');
        else if (!data.documents.length) empty(readiness, 'Your research starts with a source. Add a PDF to build your library.', 'Upload your first PDF →', '#upload');
        else {
            const message = data.attention.length ? `${data.attention.length} document${data.attention.length === 1 ? '' : 's'} need attention.`
                : data.preparing.length ? 'Your library is getting ready.' : 'Your sources are ready to explore.';
            readiness.append(node('h3', message), node('p', `${data.ready.length} ready · ${data.preparing.length} preparing · ${data.attention.length} need attention`, 'desk-readiness-summary'));
            const bar = node('div', '', 'desk-readiness-bar'); bar.setAttribute('aria-hidden', 'true');
            for (const [key, items] of [['ready', data.ready], ['preparing', data.preparing], ['attention', data.attention]]) {
                const segment = node('span', '', `desk-bar-${key}`); segment.style.width = `${100 * items.length / data.documents.length}%`; bar.append(segment);
            }
            readiness.append(bar);
            const needsWork = [...data.attention, ...data.preparing].slice(0, 2);
            for (const doc of needsWork) {
                const row = node('div', '', 'desk-attention-row');
                row.append(node('span', doc.filename), link(doc.deskState === 'attention' ? 'Review preparation ↗' : 'View progress ↗', '#upload')); readiness.append(row);
            }
            if (!needsWork.length) readiness.append(link('Ask about your documents →', '#chat', 'desk-inline-action'));
            if (data.stats) readiness.append(node('p', `${data.stats.total_pages ?? 0} document pages · ${data.stats.pending_jobs ?? 0} jobs in progress · ${data.stats.pending_page_tasks ?? 0} page tasks`, 'desk-footnote'));
        }
        const chats = el('desk-chats'); chats.replaceChildren();
        if (!data.conversations) empty(chats, 'Recent chats could not be loaded. Refresh to try again.');
        else if (!data.conversations.length) empty(chats, 'Keep a conversation with your documents. Your chats will be waiting here when you return.', 'Start a conversation →', '#chat');
        else for (const chat of data.conversations.slice(0, 3)) {
            const row = node('div', '', 'desk-work-row'), copy = node('div');
            const scope = chat.document_ids === null ? 'All documents when asked' : `${chat.document_ids?.length ?? 0} selected documents`;
            copy.append(node('strong', chat.title), node('small', `${scope} · ${date(chat.updated_at)}`));
            const resume = action('Resume ↗', () => window.VisionWorkspace.resume(chat.id)); resume.setAttribute('aria-label', `Resume ${chat.title}`);
            row.append(node('span', '▱', 'desk-row-icon'), copy, resume); chats.append(row);
        }
        const library = el('desk-library'); library.replaceChildren();
        if (!data.documents) empty(library, 'Your library could not be loaded. Refresh to try again.');
        else if (!data.documents.length) empty(library, 'A persistent home for reports, research papers and original versions.', 'Add a document →', '#upload');
        else for (const doc of data.documents.slice(0, 5)) {
            const row = node('div', '', 'desk-work-row'), copy = node('div');
            const label = doc.deskState === 'ready' ? 'Ready to ask' : doc.deskState === 'attention' ? 'Needs attention' : 'Preparing';
            copy.append(node('strong', doc.filename), node('small', `${doc.page_count ?? 0} pages · ${label}`));
            const open = doc.deskState === 'ready' ? action('Ask ↗', () => window.VisionWorkspace.useDocument(doc.id)) : link('Review ↗', '#upload', 'desk-row-action');
            open.setAttribute('aria-label', doc.deskState === 'ready' ? `Ask about ${doc.filename}` : `Review preparation for ${doc.filename}`);
            row.append(node('span', 'PDF', 'desk-pdf'), copy, open);
            library.append(row);
        }
        const findings = el('desk-saved-findings'); findings.replaceChildren();
        if (!data.saved) empty(findings, 'Saved findings could not be loaded. Refresh to try again.');
        else if (!data.saved.length) empty(findings, 'Keep an answer or comparison after inspecting its evidence. Saved findings can be reviewed and exported.', 'Explore report comparison →', '#analysis');
        else for (const finding of data.saved.slice(0, 3)) {
            const row = node('div', '', 'desk-work-row'), copy = node('div');
            copy.append(node('strong', finding.title), node('small', `${finding.kind === 'comparison' ? 'Comparison' : 'Answer'} · ${finding.reviewed ? 'User reviewed' : 'Not reviewed'} · ${date(finding.updated_at)}`));
            const open = action('Open ↗', () => window.VisionFindings.show(finding.id)); open.setAttribute('aria-label', `Open finding ${finding.title}`);
            row.append(node('span', '◇', 'desk-row-icon'), copy, open); findings.append(row);
        }
    }
    async function get(path) {
        const response = await fetch('/api/v1' + path);
        if (!response.ok) throw new Error('Unavailable'); return response.json();
    }
    function refresh() {
        if (loading) return loading;
        loading = (async () => {
            const button = el('refresh-stats-btn'); button.disabled = true;
            const status = el('dashboard-status'); status.textContent = 'Refreshing your workspace…';
            const names = ['stats', 'readiness', 'conversations', 'findings'];
            try {
                const results = await Promise.allSettled(['/stats', '/workspace/readiness', '/conversations', '/findings'].map(get));
                const data = Object.fromEntries(results.map((r, i) => [names[i], r.status === 'fulfilled' ? r.value : null]));
                render(model(data));
                const failed = results.filter(r => r.status === 'rejected').length;
                status.textContent = failed ? 'Some workspace data is unavailable. Refresh to retry; unavailable totals are shown as —.'
                    : `Updated ${new Date().toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'})} · From your saved library · Refreshes while this dashboard is open`;
            } catch { status.textContent = 'Unable to load your workspace. Refresh to try again.'; }
            finally { button.disabled = false; loading = null; }
        })(); return loading;
    }
    function setup() {
        if (installed) return; installed = true;
        el('refresh-stats-btn').addEventListener('click', refresh);
        const updateIfVisible = () => { if (!document.hidden && el('page-dashboard').classList.contains('active')) refresh(); };
        window.addEventListener('vision-library-changed', updateIfVisible);
        window.addEventListener('online', updateIfVisible);
        document.addEventListener('visibilitychange', updateIfVisible);
        setInterval(updateIfVisible, 15000);
    }
    window.VisionDashboard = {refresh, setup, model};
})();
