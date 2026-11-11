/* Public, illustrative architecture only. No owner data, requests or dependencies. */
(() => {
    'use strict';
    const root = document.getElementById('vision-wireframe');
    if (!root) return;
    const stages = [
        ['PRESERVE', 'A lasting original. Every version retained.',
            'PDFs enter a persistent library as immutable versions. Page references keep pointing to the original document, even after you upload a replacement.',
            ['Original PDFs', 'Version history', 'Durable jobs']],
        ['PREPARE', 'Read the words. See the whole page.',
            'Native text is extracted and split into page-local chunks. Rendered pages preserve visual evidence such as tables and charts; optional OCR helps when configured. Processing status stays visible.',
            ['Native text', 'Visual pages', 'Optional OCR']],
        ['INDEX', 'Different signals. A connected library.',
            'Keyword search, BGE text embeddings and ColPali visual tokens create complementary ways to find evidence. SQLite and Qdrant retain metadata and searchable representations in versioned indexes.',
            ['SQLite / FTS5', 'BGE embeddings', 'ColPali + Qdrant']],
        ['RETRIEVE', 'Find what matters to this question.',
            'Your question searches the selected documents. Eligible keyword, dense text and visual results are fused, ranked and bounded into an evidence set. Find pages returns local evidence without calling a generation provider.',
            ['Explicit document scope', 'Rank fusion', 'Local Find pages']],
        ['GROUND', 'An answer with a route back to its source.',
            'Gemini uses retrieved text and page images to compose an answer. References are checked against supplied evidence IDs and resolve to original versions and pages. A valid citation is a reference, not independent proof of accuracy.',
            ['Evidence-bounded generation', 'Version + page citations', 'Original-page viewer']],
        ['KEEP', 'Turn a useful answer into lasting work.',
            'Inspect cited pages, compare reported fields across two to four document versions, and save useful answers or comparisons as findings. Review and export JSON, CSV or Markdown with source references.',
            ['Report comparisons', 'Saved findings', 'Review + export']],
    ];
    const buttons = [...root.querySelectorAll('[data-wire-stage]')];
    const modules = [...root.querySelectorAll('[data-wire-module]')];
    const routes = [...root.querySelectorAll('[data-wire-route]')];
    const play = document.getElementById('wire-play');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const scroll = root.querySelector('.wire-scroll');
    let index = 0, timer = null, visible = false, paused = false;

    function select(next, manual = false) {
        if (!Number.isInteger(next) || !stages[next]) return;
        index = next;
        const [name, title, description, tags] = stages[index];
        buttons.forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.wireStage) === index)));
        modules.forEach(module => module.classList.toggle('is-active', Number(module.dataset.wireModule) === index));
        routes.forEach(route => route.classList.toggle('is-active', Number(route.dataset.wireRoute) === index));
        document.getElementById('wire-step').textContent = `${String(index + 1).padStart(2, '0')} / ${name}`;
        document.getElementById('wire-title').textContent = title;
        document.getElementById('wire-description').textContent = description;
        document.getElementById('wire-tags').replaceChildren(...tags.map(tag => {
            const span = document.createElement('span'); span.textContent = tag; return span;
        }));
        // Follow the selected module inside the diagram, never move the page.
        if (scroll.scrollWidth > scroll.clientWidth) {
            scroll.scrollTo({left: Math.max(0, scroll.scrollWidth / 6 * (index + .5) - scroll.clientWidth / 2), behavior: manual && !motion.matches ? 'smooth' : 'instant'});
        }
        if (manual) {
            paused = true; sync();
            document.getElementById('wire-announcement').textContent = `Stage ${index + 1}: ${title} ${description}`;
        }
    }
    function sync() {
        if (timer !== null) { clearInterval(timer); timer = null; }
        const running = visible && !document.hidden && !paused && !motion.matches;
        root.dataset.running = String(running);
        play.textContent = paused ? 'Play animation' : 'Pause animation';
        play.hidden = motion.matches;
        document.getElementById('wire-mode').textContent = motion.matches ? 'Reduced motion · select a stage' : paused ? 'Paused · explore any stage' : 'Guided system tour';
        if (running) timer = setInterval(() => select((index + 1) % stages.length), 4200);
    }
    buttons.forEach(button => button.addEventListener('click', () => select(Number(button.dataset.wireStage), true)));
    play.addEventListener('click', () => { paused = !paused; sync(); });
    // Let visitors inspect or pan the drawing without the tour pulling it away.
    const pauseForInspection = () => { paused = true; sync(); };
    scroll.addEventListener('pointerdown', pauseForInspection);
    scroll.addEventListener('wheel', pauseForInspection, {passive: true});
    motion.addEventListener('change', sync);
    document.addEventListener('visibilitychange', sync);
    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver(entries => {
            visible = entries.some(entry => entry.isIntersecting); sync();
        }, {threshold: .15});
        observer.observe(root);
        window.addEventListener('pagehide', () => { observer.disconnect(); if (timer !== null) clearInterval(timer); timer = null; });
        window.addEventListener('pageshow', () => observer.observe(root));
    } else visible = true;
    root.dataset.enhanced = 'true'; select(0); sync();
})();
