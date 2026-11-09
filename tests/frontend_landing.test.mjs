import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function load(hash, search = '') {
    const redirected = [], handlers = {};
    const location = {hash, search, replace: url => redirected.push(url)};
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/landing.js', 'utf8'), {
        location, Set, window: {addEventListener: (name, handler) => { handlers[name] = handler; }},
    });
    return {redirected, handlers, location};
}

test('project sections stay on the landing page rather than opening the workspace', () => {
    for (const hash of ['', '#product', '#how-it-works', '#features', '#architecture', '#documentation']) {
        assert.deepEqual(load(hash).redirected, []);
    }
});

test('legacy document bookmarks enter the workspace and preserve their query', () => {
    for (const hash of ['#chat', '#documents', '#analysis', '#findings', '#upload', '#dashboard']) {
        assert.deepEqual(load(hash, '?fresh=123').redirected, ['/workspace?fresh=123' + hash]);
    }
});

test('hash navigation is handled without permitting arbitrary redirect destinations', () => {
    const f = load('#product');
    f.location.hash = '#documents'; f.handlers.hashchange();
    assert.deepEqual(f.redirected, ['/workspace#documents']);
    assert.deepEqual(load('#https://untrusted.invalid').redirected, []);
});

function demo() {
    const names = ['dashboard', 'upload', 'chat', 'documents'];
    const panels = Object.fromEntries(names.map(name => ['demo-' + name, {hidden: name !== 'dashboard'}]));
    const tabs = names.map(name => ({
        dataset: {demo: name}, attributes: {'aria-controls': 'demo-' + name}, handlers: {},
        setAttribute(key, value) { this.attributes[key] = value; },
        getAttribute(key) { return this.attributes[key]; },
        addEventListener(key, value) { this.handlers[key] = value; },
        focus() { this.focused = true; },
    }));
    const next = {dataset: {go: 'chat'}, addEventListener(_, action) { this.click = action; }};
    const citation = {addEventListener(_, action) { this.click = action; }};
    const feedback = {}, source = {classList: {add(value) { source.highlight = value; }},
        querySelector() { return feedback; }, scrollIntoView() { this.scrolled = true; }};
    const windowNode = {scrollIntoView() { this.scrolled = true; }};
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/landing.js', 'utf8'), {
        location: {hash: '', search: ''}, window: {addEventListener() {}},
        document: {
            querySelectorAll(selector) { return selector === '[data-demo]' ? tabs : selector === '[data-go]' ? [next] : [citation]; },
            getElementById(id) { return id === 'demo-source' ? source : panels[id]; },
            querySelector() { return windowNode; },
        },
    });
    return {tabs, panels, next, citation, source, feedback};
}

test('walkthrough switches one panel at a time and supports wrapping keyboard navigation', () => {
    const d = demo();
    d.tabs[1].handlers.click();
    assert.equal(d.panels['demo-upload'].hidden, false);
    assert.equal(d.panels['demo-dashboard'].hidden, true);
    assert.equal(d.tabs[1].attributes['aria-selected'], 'true');
    assert.equal(d.tabs[0].tabIndex, -1);
    let prevented = false;
    d.tabs[0].handlers.keydown({key: 'ArrowLeft', preventDefault() { prevented = true; }});
    assert.equal(prevented, true);
    assert.equal(d.tabs[3].focused, true);
    assert.equal(d.panels['demo-documents'].hidden, false);
    d.tabs[3].handlers.keydown({key: 'Home', preventDefault() {}});
    assert.equal(d.panels['demo-dashboard'].hidden, false);
});

test('workflow next actions enter chat and citations expose the original source context', () => {
    const d = demo();
    d.next.click();
    assert.equal(d.panels['demo-chat'].hidden, false);
    assert.equal(d.tabs[2].focused, true);
    d.citation.click();
    assert.equal(d.source.highlight, 'source-highlight');
    assert.match(d.feedback.textContent, /v1 · page 12/);
    assert.equal(d.source.scrolled, true);
});
