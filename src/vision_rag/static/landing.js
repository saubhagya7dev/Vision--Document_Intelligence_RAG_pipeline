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
})();
