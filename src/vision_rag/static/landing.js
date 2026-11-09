/* The public project page never loads the owner's library or session state. */
(() => {
    'use strict';
    // Preserve old root hash bookmarks without confusing project-section anchors.
    const workspaceRoutes = new Set(['chat', 'documents', 'analysis', 'findings', 'upload', 'dashboard']);
    const routeLegacyBookmark = () => {
        if (workspaceRoutes.has(location.hash.slice(1))) location.replace('/workspace' + location.search + location.hash);
    };
    routeLegacyBookmark();
    window.addEventListener('hashchange', routeLegacyBookmark);

    // The demonstration is local, fictional content: no owner API requests.
    if (typeof document === 'undefined') return;
    const tabs = [...document.querySelectorAll('[data-demo]')];
    function showDemo(name, focus = false) {
        const selected = tabs.find(tab => tab.dataset.demo === name);
        if (!selected) return;
        tabs.forEach(tab => {
            const active = tab === selected;
            tab.setAttribute('aria-selected', String(active));
            tab.tabIndex = active ? 0 : -1;
            document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
        });
        if (focus) selected.focus();
    }
    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => showDemo(tab.dataset.demo));
        tab.addEventListener('keydown', event => {
            let next;
            if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
            if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
            if (event.key === 'Home') next = 0;
            if (event.key === 'End') next = tabs.length - 1;
            if (next === undefined) return;
            event.preventDefault(); showDemo(tabs[next].dataset.demo, true);
        });
    });
    document.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => {
        showDemo(button.dataset.go, true);
        document.querySelector('.demo-window').scrollIntoView({block: 'nearest'});
    }));
    document.querySelectorAll('.citation-demo').forEach(button => button.addEventListener('click', () => {
        const source = document.getElementById('demo-source');
        source.classList.add('source-highlight');
        source.querySelector('.source-feedback').textContent = 'Source located: Juniper-2025.pdf · v1 · page 12. Revenue is highlighted.';
        source.scrollIntoView({block: 'nearest'});
    }));
})();
