/* Adjustable evidence width, saved per browser. No document content is stored here. */
(() => {
    'use strict';
    function bounds(total) { const max = Math.max(260, Math.min(720, Math.floor(total - 340))); return {min:260, max}; }
    function clamp(value, total) { const {min,max} = bounds(total); return Math.round(Math.min(max, Math.max(min, Number.isFinite(value) ? value : total * .34))); }
    function setup(workbench, panel, handle) {
        let preferred = null, drag = null;
        try { const saved = localStorage.getItem('vr_reader_width'); if (saved !== null && Number.isFinite(Number(saved))) preferred = Number(saved); } catch { /* Optional preference. */ }
        function apply(value = preferred) {
            const total = workbench.clientWidth;
            if (!total) return;
            const width = clamp(value === null ? NaN : value, total), limits = bounds(total);
            workbench.style.setProperty('--reader-width', `${width}px`);
            handle.setAttribute('aria-valuemin', limits.min); handle.setAttribute('aria-valuemax', limits.max);
            handle.setAttribute('aria-valuenow', width); handle.setAttribute('aria-valuetext', `${width} pixels`);
            return width;
        }
        function save() { try { localStorage.setItem('vr_reader_width', String(preferred)); } catch { /* Resizing still works. */ } }
        function finish() { if (!drag) return; drag = null; document.body.classList.remove('reader-resizing'); save(); }
        handle.addEventListener('pointerdown', event => {
            if (event.button !== 0) return;
            event.preventDefault(); handle.focus();
            drag = {x:event.clientX, width:panel.getBoundingClientRect().width};
            handle.setPointerCapture(event.pointerId); document.body.classList.add('reader-resizing');
        });
        handle.addEventListener('pointermove', event => { if (drag) preferred = apply(drag.width + drag.x - event.clientX); });
        for (const type of ['pointerup','pointercancel','lostpointercapture']) handle.addEventListener(type, finish);
        handle.addEventListener('keydown', event => {
            const current = Number(handle.getAttribute('aria-valuenow')), step = event.shiftKey ? 50 : 20, limits = bounds(workbench.clientWidth);
            const values = {ArrowLeft:current + step, ArrowRight:current - step, Home:limits.min, End:limits.max};
            if (!(event.key in values)) return;
            event.preventDefault(); preferred = apply(values[event.key]); save();
        });
        handle.addEventListener('dblclick', () => { preferred = null; try { localStorage.removeItem('vr_reader_width'); } catch {} apply(); });
        new ResizeObserver(() => apply()).observe(workbench);
        window.addEventListener('vision-route-changed', finish);
        apply();
    }
    window.VisionReaderLayout = {bounds, clamp, setup};
})();
