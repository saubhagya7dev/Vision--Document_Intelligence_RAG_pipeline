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
    for (const hash of ['', '#product', '#features', '#architecture', '#documentation']) {
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
