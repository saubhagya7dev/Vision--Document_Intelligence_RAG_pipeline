import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function load(payload = {}, failed = []) {
    const make = () => ({children: [], style: {}, attributes: {}, handlers: {},
        classList: {contains: () => true},
        set textContent(value) { this.text = String(value); }, get textContent() { return this.text || ''; },
        set innerHTML(_) { throw new Error('Untrusted dashboard content must never be parsed as HTML'); },
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, callback) { this.handlers[name] = callback; }});
    const ids = new Map(); const calls = []; const opened = [];
    const document = {hidden: false, createElement: make, addEventListener() {},
        getElementById(id) { if (!ids.has(id)) ids.set(id, make()); return ids.get(id); }};
    const window = {addEventListener() {}, VisionWorkspace: {resume: id => opened.push(['chat', id]), useDocument: id => opened.push(['document', id])},
        VisionFindings: {show: id => opened.push(['finding', id])}};
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/dashboard.js', 'utf8'), {
        window, document, setInterval() {},
        fetch: async path => { calls.push(path); return {ok: !failed.includes(path), json: async () => payload[path]}; },
    });
    const nodes = parent => [parent, ...parent.children.flatMap(nodes)];
    return {api: window.VisionDashboard, document, ids, calls, opened, nodes};
}

test('readiness distinguishes searchable documents from preparation and failed index work', () => {
    const {api} = load();
    const state = api.model({readiness: {search_enabled: true, index: {state: 'failed'}, documents: [
        {id: 'a', state: 'ready', search_state: 'ready'},
        {id: 'b', state: 'ready', search_state: 'preparing'},
        {id: 'c', state: 'running', search_state: 'reading'},
        {id: 'd', state: 'failed', search_state: 'failed'},
        {id: 'e', state: 'ready', search_state: 'empty'},
    ]}});
    assert.equal(state.ready.length, 1);
    assert.equal(state.preparing.length, 1);
    assert.equal(state.attention.length, 3);
    const disabled = api.model({readiness: {search_enabled: false, documents: [{search_state: 'preparing'}]}});
    assert.equal(disabled.attention.length, 1);
});

test('missing data remains unknown and only saved findings contribute to the total', () => {
    const {api} = load();
    const missing = api.model();
    assert.equal(missing.documents, null); assert.equal(missing.saved, null); assert.equal(missing.stats, null);
    const findings = [
        {id: 'old', state: 'saved', updated_at: '2026-11-01'},
        {id: 'draft', state: 'draft', updated_at: '2026-11-11'},
        {id: 'new', state: 'saved', updated_at: '2026-11-10'},
    ];
    const state = api.model({findings});
    assert.deepEqual(Array.from(state.saved, item => item.id), ['new', 'old']);
    assert.equal(findings[0].id, 'old');
});

test('refresh is coalesced and partial failure preserves independent sections without invented totals', async () => {
    const d = load({'/api/v1/workspace/readiness': {search_enabled: true, documents: [{id: 'a', filename: 'Report.pdf', page_count: 2, search_state: 'ready'}]},
        '/api/v1/conversations': [], '/api/v1/findings': []}, ['/api/v1/stats']);
    const first = d.api.refresh(), second = d.api.refresh();
    assert.equal(first, second);
    assert.equal(d.document.getElementById('refresh-stats-btn').disabled, true);
    await first;
    assert.equal(d.calls.length, 4);
    assert.equal(d.ids.get('desk-ready').textContent, '1');
    assert.equal(d.ids.get('desk-answers').textContent, '—');
    assert.match(d.ids.get('dashboard-status').textContent, /Some workspace data is unavailable/);
    assert.equal(d.ids.get('refresh-stats-btn').disabled, false);
});

test('persisted titles are text and each dashboard action opens the correct record', async () => {
    const filename = '<img src=x onerror=alert(1)>.pdf';
    const d = load({'/api/v1/stats': {completed_queries: 3, total_pages: 2},
        '/api/v1/workspace/readiness': {search_enabled: true, documents: [{id: 'document-id', filename, page_count: 2, search_state: 'ready'}]},
        '/api/v1/conversations': [{id: 'chat-id', title: 'Research <report>', document_ids: ['document-id']}],
        '/api/v1/findings': [{id: 'finding-id', title: 'Revenue <finding>', kind: 'answer', state: 'saved'}]});
    await d.api.refresh();
    assert.ok(d.nodes(d.ids.get('desk-library')).some(n => n.textContent === filename));
    for (const id of ['desk-chats', 'desk-library', 'desk-saved-findings']) {
        const button = d.nodes(d.ids.get(id)).find(n => n.attributes['aria-label']);
        await button.handlers.click();
    }
    assert.deepEqual(d.opened, [['chat', 'chat-id'], ['document', 'document-id'], ['finding', 'finding-id']]);
    assert.equal(d.ids.get('desk-findings').textContent, '1');
});

test('an empty library provides real starting actions and zeroes rather than fictional activity', async () => {
    const d = load({'/api/v1/stats': {completed_queries: 0}, '/api/v1/workspace/readiness': {documents: [], search_enabled: true},
        '/api/v1/conversations': [], '/api/v1/findings': []});
    await d.api.refresh();
    assert.equal(d.ids.get('desk-ready').textContent, '0');
    assert.equal(d.ids.get('desk-answers').textContent, '0');
    assert.ok(d.nodes(d.ids.get('desk-readiness-content')).some(n => n.href === '#upload'));
    assert.ok(d.nodes(d.ids.get('desk-chats')).some(n => n.href === '#chat'));
});
