// Behavioral checks for explicit selection and recovery, without paid inference.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

class Element {
    constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.value = ''; this.classList = {contains: () => true}; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    focus() {}
}
function fixture() {
    const elements = new Map();
    const el = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
    let current = {document_ids: []}, busy = false, failSave = false;
    const state = {documents: [{id: 'one', filename: 'report.pdf', search_state: 'ready', state: 'ready', version: 1, page_count: 2}], search_enabled: true, index: {state: 'ready'}};
    const saves = [], errors = [];
    const sandbox = {window: {addEventListener() {}}, document: {getElementById: el, createElement: tag => new Element(tag)}, setInterval() {}, encodeURIComponent, Set};
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/documents.js', 'utf8'), sandbox);
    const selection = sandbox.window.createDocumentSelection(async () => state, () => current,
        async ids => { if (failSave) throw new Error('offline'); current = {document_ids: ids}; saves.push(ids); },
        () => busy, error => errors.push(error.message));
    selection.setup();
    return {selection, state, el, saves, errors, setBusy: value => { busy = value; }, failSave: () => { failSave = true; }};
}

test('clearing selection remains empty and disables sending rather than searching everything', async () => {
    const f = fixture(); await f.selection.refresh(); await f.selection.change(['one']);
    assert.equal(f.selection.canSend(), true);
    await f.selection.change([]);
    assert.equal(f.saves.at(-1).length, 0);
    assert.equal(f.selection.canSend(), false);
    assert.equal(f.el('send-btn').disabled, true);
});

test('saved PDF is blocked until the selected version becomes searchable', async () => {
    const f = fixture(); f.state.documents[0].search_state = 'preparing';
    await f.selection.refresh(); await f.selection.change(['one']);
    assert.equal(f.selection.canSend(), false);
    assert.equal(f.el('send-readiness').textContent, 'Waiting for documents');
    f.state.documents[0].search_state = 'ready'; await f.selection.refresh();
    assert.equal(f.selection.canSend(), true);
    f.state.documents = []; await f.selection.refresh();
    assert.equal(f.selection.canSend(), false, 'deleted sources must not silently broaden scope');
});

test('failed selection stays in the open picker and retains the old selection', async () => {
    const f = fixture(); await f.selection.refresh(); await f.selection.change(['one']);
    await f.selection.pick(); f.failSave();
    await f.el('apply-documents').listeners.click();
    assert.equal(f.el('document-picker').open, true);
    assert.equal(f.selection.canSend(), true);
    assert.match(f.el('document-picker-status').textContent, /Selection not saved/);
    assert.deepEqual(f.errors, ['offline']);
});

test('running questions cannot change selection and ready bulk selection is capped at six', async () => {
    const f = fixture(); await f.selection.refresh(); f.setBusy(true);
    await f.selection.change(['one']); assert.equal(f.saves.length, 0);
    f.setBusy(false);
    f.state.documents = Array.from({length: 8}, (_, i) => ({id: String(i), filename: `${i}.pdf`, search_state: 'ready', page_count: 1}));
    await f.selection.pick(); f.el('select-ready-documents').listeners.click();
    await f.el('apply-documents').listeners.click();
    assert.equal(f.saves.at(-1).length, 6);
});
