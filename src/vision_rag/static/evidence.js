/* Version-specific evidence viewer. All labels are rendered as text. */
window.createEvidenceViewer = function(api, getCurrent, report, prefix) {
    'use strict';
    prefix = prefix || '';
    const el = id => document.getElementById(prefix + id);
    const encode = encodeURIComponent;
    let viewer = null, viewerToken = 0, savedScroll = null, saveTimer;
    function button(text, action) {
        const b = document.createElement('button'); b.type = 'button'; b.className = 'job-action';
        b.textContent = text; b.addEventListener('click', action); return b;
    }
    function saveViewer() {
        const current = getCurrent();
        clearTimeout(saveTimer);
        if (!current || !viewer) return;
        const id = current.id;
        const state = {version_id: viewer.id, page: Number(el('viewer-page').value),
            zoom: Number(el('viewer-zoom').value), scroll_top: el('viewer-scroll').scrollTop,
            scroll_left: el('viewer-scroll').scrollLeft};
        current.viewer = state;
        saveTimer = setTimeout(() => api(`/conversations/${encode(id)}`, 'PATCH', {viewer: state}).catch(report), 250);
    }
    function page(number, restore = false) {
        const current = getCurrent();
        if (!viewer) return;
        number = Math.max(1, Math.min(viewer.page_count, Number(number) || 1));
        el('viewer-page').value = number; el('viewer-page').max = viewer.page_count;
        el('viewer-prev').disabled = number === 1; el('viewer-next').disabled = number === viewer.page_count;
        el('viewer-pages').textContent = `/ ${viewer.page_count}`;
        el('viewer-status').textContent = `Loading page ${number}…`;
        savedScroll = restore ? current?.viewer : {scroll_top: 0, scroll_left: 0};
        el('viewer-image').src = `/api/v1/versions/${encode(viewer.id)}/pages/${number}`;
        el('viewer-image').alt = `${viewer.filename}, page ${number}`;
        el('viewer-image').style.width = `${Number(el('viewer-zoom').value) * 100}%`;
        const thumbnails = el('viewer-thumbnails'); thumbnails.replaceChildren();
        for (let i = Math.max(1, number - 2); i <= Math.min(viewer.page_count, number + 2); i++) {
            const b = button(`Page ${i}`, () => page(i));
            b.setAttribute('aria-current', i === number ? 'page' : 'false');
            const img = document.createElement('img'); img.alt = ''; img.loading = 'lazy';
            img.src = `/api/v1/versions/${encode(viewer.id)}/pages/${i}?thumbnail=true`;
            b.prepend(img); thumbnails.append(b);
        }
        if (!restore) saveViewer();
    }
    async function showEvidence(source, restore = false) {
        const current = getCurrent();
        const token = ++viewerToken;
        try {
            el('viewer-status').textContent = 'Opening the cited document version…';
            const info = await api(`/versions/${encode(source.version_id)}/info`);
            if (token !== viewerToken) return;
            viewer = info; el('viewer-controls').hidden = false;
            el('viewer-document').textContent = `${info.filename} · version ${info.id.slice(0, 8)}`;
            el('viewer-original').href = `/api/v1/versions/${encode(info.id)}/file`;
            const zoom = String(restore ? current.viewer.zoom || 1 : 1);
            if (![...el('viewer-zoom').options].some(option => option.value === zoom)) {
                el('viewer-zoom').add(new Option(`${Number(zoom) * 100}%`, zoom));
            }
            el('viewer-zoom').value = zoom;
            page(source.page, restore);
            if (!restore) el('viewer-controls').scrollIntoView({block: 'nearest'});
        } catch (error) {
            if (token !== viewerToken) return;
            el('viewer-controls').hidden = true; el('viewer-status').textContent = `Evidence unavailable: ${error.message}. The saved citation is retained.`;
        }
    }
    function setup() {
        el('viewer-prev').addEventListener('click', () => page(Number(el('viewer-page').value) - 1));
        el('viewer-next').addEventListener('click', () => page(Number(el('viewer-page').value) + 1));
        el('viewer-page').addEventListener('change', e => page(e.target.value));
        el('viewer-zoom').addEventListener('change', () => { el('viewer-image').style.width = `${Number(el('viewer-zoom').value) * 100}%`; saveViewer(); });
        el('viewer-scroll').addEventListener('scroll', saveViewer);
        el('viewer-image').addEventListener('load', () => {
            if (!viewer) return;
            el('viewer-status').textContent = 'Evidence page ready.';
            if (savedScroll) { el('viewer-scroll').scrollTop = savedScroll.scroll_top || 0; el('viewer-scroll').scrollLeft = savedScroll.scroll_left || 0; savedScroll = null; }
            saveViewer();
        });
        el('viewer-image').addEventListener('error', () => { el('viewer-status').textContent = 'Page preview failed. Try another page or open the original PDF.'; });
    }
    function reset() {
        clearTimeout(saveTimer); ++viewerToken; viewer = null;
        savedScroll = null;
        el('viewer-controls').hidden = true;
        el('viewer-status').textContent = '';
    }
    return {show: showEvidence, setup, reset};
};
