import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function load({reduced = false, narrow = false, observer = true} = {}) {
    const make = (dataset = {}) => ({dataset, handlers: {}, attributes: {}, children: [],
        classList: {toggle(name, value) { this[name] = value; }},
        addEventListener(name, action) { this.handlers[name] = action; },
        setAttribute(name, value) { this.attributes[name] = value; },
        replaceChildren(...children) { this.children = children; }});
    const buttons = Array.from({length: 6}, (_, i) => make({wireStage: String(i)}));
    const modules = Array.from({length: 6}, (_, i) => make({wireModule: String(i)}));
    const routes = Array.from({length: 6}, (_, i) => make({wireRoute: String(i)}));
    const scroll = Object.assign(make(), {scrollWidth: 1120, clientWidth: narrow ? 320 : 1120,
        scrollTo(value) { this.position = value; }});
    const root = make();
    root.querySelectorAll = selector => ({'[data-wire-stage]': buttons, '[data-wire-module]': modules, '[data-wire-route]': routes})[selector];
    root.querySelector = () => scroll;
    const ids = Object.fromEntries(['wire-play', 'wire-mode', 'wire-step', 'wire-title', 'wire-description', 'wire-tags', 'wire-announcement'].map(id => [id, make()]));
    const motion = Object.assign(make(), {matches: reduced});
    const document = Object.assign(make(), {hidden: false,
        getElementById(id) { return id === 'vision-wireframe' ? root : ids[id]; },
        createElement() { return make(); }});
    const window = Object.assign(make(), {matchMedia: () => motion});
    let intersection;
    class Observer {
        constructor(callback) { intersection = callback; }
        observe() { this.observing = true; }
        disconnect() { this.observing = false; }
    }
    if (observer) window.IntersectionObserver = Observer;
    const timers = new Map(); let serial = 0;
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/wireframe.js', 'utf8'), {
        document, window, IntersectionObserver: Observer,
        setInterval(callback) { timers.set(++serial, callback); return serial; },
        clearInterval(id) { timers.delete(id); },
    });
    return {root, ids, buttons, modules, routes, scroll, motion, document, window, timers,
        visible(value) { intersection([{isIntersecting: value}]); },
        tick() { [...timers.values()].forEach(callback => callback()); }};
}

test('tour waits until visible and cycles all six stages without stealing focus', () => {
    const d = load();
    assert.equal(d.timers.size, 0);
    assert.equal(d.root.dataset.running, 'false');
    d.visible(true);
    assert.equal(d.timers.size, 1);
    for (let i = 1; i <= 6; i++) {
        d.tick();
        assert.equal(d.buttons[i % 6].attributes['aria-pressed'], 'true');
        assert.equal(d.modules[i % 6].classList['is-active'], true);
    }
    assert.equal(d.ids['wire-announcement'].textContent, undefined);
    d.visible(false);
    assert.equal(d.timers.size, 0);
    assert.equal(d.root.dataset.running, 'false');
});

test('manual selection pauses playback and announces the selected stage', () => {
    const d = load({narrow: true}); d.visible(true);
    d.buttons[3].handlers.click();
    assert.equal(d.timers.size, 0);
    assert.equal(d.ids['wire-play'].textContent, 'Play animation');
    assert.match(d.ids['wire-description'].textContent, /without calling a generation provider/);
    assert.match(d.ids['wire-announcement'].textContent, /Stage 4/);
    assert.equal(d.buttons.filter(b => b.attributes['aria-pressed'] === 'true').length, 1);
    assert.ok(d.scroll.position.left > 0);
    d.ids['wire-play'].handlers.click();
    assert.equal(d.timers.size, 1);
});

test('reduced motion keeps every stage inspectable without automatic animation', () => {
    const d = load({reduced: true}); d.visible(true);
    assert.equal(d.timers.size, 0);
    assert.equal(d.ids['wire-play'].hidden, true);
    d.buttons[4].handlers.click();
    assert.match(d.ids['wire-description'].textContent, /not independent proof/);
    assert.equal(d.modules[4].classList['is-active'], true);
    d.motion.matches = false; d.motion.handlers.change();
    assert.equal(d.ids['wire-play'].hidden, false);
    assert.equal(d.timers.size, 0); // A manual pause survives a preference change.
});

test('visibility and lifecycle changes do not leak or multiply tour timers', () => {
    const d = load(); d.visible(true); d.visible(true);
    assert.equal(d.timers.size, 1);
    d.document.hidden = true; d.document.handlers.visibilitychange();
    assert.equal(d.timers.size, 0);
    d.document.hidden = false; d.document.handlers.visibilitychange();
    assert.equal(d.timers.size, 1);
    d.window.handlers.pagehide();
    assert.equal(d.timers.size, 0);
    d.window.handlers.pageshow(); d.visible(true);
    assert.equal(d.timers.size, 1);
});

test('panning the diagram pauses the guided tour rather than fighting the visitor', () => {
    const d = load(); d.visible(true);
    d.scroll.handlers.pointerdown();
    assert.equal(d.timers.size, 0);
    d.visible(false); d.visible(true);
    assert.equal(d.timers.size, 0);
    d.ids['wire-play'].handlers.click();
    d.scroll.handlers.wheel();
    assert.equal(d.root.dataset.running, 'false');
});

test('observer fallback can animate and a missing illustration is a safe no-op', () => {
    const d = load({observer: false});
    assert.equal(d.root.dataset.running, 'true');
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/wireframe.js', 'utf8'), {
        document: {getElementById() { return null; }},
    });
});
