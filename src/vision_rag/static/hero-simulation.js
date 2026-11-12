/* Local illustration: suspend when unseen; always respect reduced motion. */
(() => {
    'use strict';
    const root = document.getElementById('hero-simulation');
    if (!root) return;
    const button = document.getElementById('hero-motion');
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    let visible = false, paused = false;
    function sync() {
        root.dataset.running = String(visible && !paused && !document.hidden && !preference.matches);
        button.hidden = preference.matches;
        button.textContent = paused ? 'Play motion' : 'Pause motion';
    }
    button.addEventListener('click', () => { paused = !paused; sync(); });
    preference.addEventListener('change', sync);
    document.addEventListener('visibilitychange', sync);
    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver(entries => { visible = entries.some(entry => entry.isIntersecting); sync(); }, {threshold: .15});
        observer.observe(root);
        window.addEventListener('pagehide', () => { visible = false; observer.disconnect(); sync(); });
        window.addEventListener('pageshow', () => observer.observe(root));
    } else visible = true;
    sync();
})();
