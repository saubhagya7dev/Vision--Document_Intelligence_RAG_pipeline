import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function load(prefix = '') {
    const ids = new Map(), calls = [], timers = new Map(); let serial = 0;
    function element() { return {style: {}, handlers: {}, children: [], options: [], value: '1',
        scrollTop: 0, scrollLeft: 0, clientWidth: 632, clientHeight: 732,
        naturalWidth: 600, naturalHeight: 900,
        addEventListener(name, callback) { this.handlers[name] = callback; },
        add(option) { this.options.push(option); },
        replaceChildren() { this.children = []; }, prepend(node) { this.children.unshift(node); },
        append(node) { this.children.push(node); }, setAttribute(name, value) { this[name] = value; }, scrollIntoView() {}}; }
    const document = {getElementById(id) { if (!ids.has(id)) ids.set(id, element()); return ids.get(id); }, createElement: element};
    const window = {};
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/evidence.js', 'utf8'), {
        window, document, Option: function(text, value) { this.text = text; this.value = value; },
        setTimeout(callback) { timers.set(++serial, callback); return serial; }, clearTimeout(id) { timers.delete(id); },
    });
    const current = {id: 'chat-a', viewer: {}};
    const api = async (path, method, body) => {
        calls.push({path, method, body});
        return {id: 'version-a', filename: 'Original.pdf', page_count: 5};
    };
    const viewer = window.createEvidenceViewer(api, () => prefix ? null : current, error => { throw error; }, prefix);
    viewer.setup();
    return {viewer, ids, calls, timers, current, el: id => document.getElementById(prefix + id),
        save() { [...timers.values()].forEach(callback => callback()); timers.clear(); }};
}

test('fit page uses the reading canvas and persists a bounded zoom for the original version', async () => {
    const d = load(); await d.viewer.show({version_id: 'version-a', page: 2});
    d.el('viewer-scroll').scrollTop = 200;
    d.el('viewer-fit-page').handlers.click(); d.save();
    const ratio = Number(d.el('viewer-zoom').value);
    assert.ok(Math.abs(ratio - 700 * 600 / 900 / 600) < .001);
    assert.equal(d.el('viewer-scroll').scrollTop, 0);
    const saved = d.calls.findLast(call => call.method === 'PATCH');
    assert.equal(saved.body.viewer.version_id, 'version-a');
    assert.equal(saved.body.viewer.page, 2);
    assert.equal(saved.body.viewer.zoom, ratio);
    assert.match(d.el('viewer-image').src, /versions\/version-a\/pages\/2$/);
});

test('fit width restores full canvas width after fit page and resets horizontal panning', async () => {
    const d = load(); await d.viewer.show({version_id: 'version-a', page: 3});
    d.el('viewer-fit-page').handlers.click();
    d.el('viewer-scroll').scrollLeft = 300;
    d.el('viewer-fit-width').handlers.click();
    assert.equal(d.el('viewer-zoom').value, '1');
    assert.equal(d.el('viewer-image').style.width, '100%');
    assert.equal(d.el('viewer-scroll').scrollLeft, 0);
});

test('extreme page proportions cannot persist zoom outside the viewer contract', async () => {
    const d = load(); await d.viewer.show({version_id: 'version-a', page: 1});
    d.el('viewer-image').naturalHeight = 100000;
    d.el('viewer-fit-page').handlers.click();
    assert.equal(d.el('viewer-zoom').value, '0.25');
    d.el('viewer-image').naturalWidth = 0;
    d.el('viewer-fit-width').handlers.click();
    d.el('viewer-fit-page').handlers.click();
    assert.equal(d.el('viewer-zoom').value, '1');
});

test('findings share fit controls without writing conversation viewer state', async () => {
    const d = load('finding-'); await d.viewer.show({version_id: 'version-a', page: 99});
    d.el('viewer-fit-page').handlers.click(); d.save();
    assert.match(d.el('viewer-image').src, /pages\/5$/);
    assert.equal(d.calls.filter(call => call.method === 'PATCH').length, 0);
    d.viewer.reset();
    assert.equal(d.el('viewer-controls').hidden, true);
});
