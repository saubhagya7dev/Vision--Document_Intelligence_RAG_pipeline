import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function load(reduced = false) {
    const root = {dataset: {}}, button = {addEventListener(_, action) { this.click = action; }};
    const motion = {matches: reduced, addEventListener(_, action) { this.change = action; }};
    const handlers = {}, document = {hidden: false, getElementById: id => id === 'hero-simulation' ? root : button,
        addEventListener(name, action) { handlers[name] = action; }};
    let observe;
    class Observer { constructor(callback) { observe = callback; } observe() {} disconnect() {} }
    const window = {IntersectionObserver: Observer, matchMedia: () => motion, addEventListener(name, action) { handlers[name] = action; }};
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/hero-simulation.js', 'utf8'), {document, window, IntersectionObserver: Observer});
    return {root, button, motion, document, handlers, visible(value) { observe([{isIntersecting: value}]); }};
}

test('hero motion runs only in view and supports a persistent manual pause', () => {
    const d = load(); assert.equal(d.root.dataset.running, 'false');
    d.visible(true); assert.equal(d.root.dataset.running, 'true');
    d.button.click(); assert.equal(d.root.dataset.running, 'false');
    d.visible(false); d.visible(true); assert.equal(d.root.dataset.running, 'false');
    d.button.click(); assert.equal(d.root.dataset.running, 'true');
    d.document.hidden = true; d.handlers.visibilitychange(); assert.equal(d.root.dataset.running, 'false');
});

test('reduced motion remains static and page lifecycle events suspend the illustration', () => {
    const d = load(true); d.visible(true);
    assert.equal(d.root.dataset.running, 'false'); assert.equal(d.button.hidden, true);
    d.motion.matches = false; d.motion.change(); assert.equal(d.root.dataset.running, 'true');
    d.handlers.pagehide(); assert.equal(d.root.dataset.running, 'false');
    d.handlers.pageshow(); d.visible(true); assert.equal(d.root.dataset.running, 'true');
});
