/* Access tokens are submitted once and never stored in browser storage or URLs. */
(() => {
    'use strict';
    const originalFetch = window.fetch.bind(window);
    let pending = null, checking = null, resolveLogin;
    const dialog = () => document.getElementById('session-dialog');
    function ready() {
        if (!checking) checking = check().finally(() => { checking = null; });
        return checking;
    }
    async function check() {
        if (pending) return pending;
        const response = await originalFetch('/api/v1/session');
        if (!response.ok) throw new Error('Session service unavailable');
        const state = await response.json();
        document.getElementById('sign-out').hidden = !state.required;
        if (state.authenticated) return true;
        pending = new Promise(resolve => { resolveLogin = resolve; });
        dialog().showModal(); document.getElementById('session-token').focus();
        return pending;
    }
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        if (response.status === 401 && !String(args[0]).endsWith('/api/v1/session')) {
            ready().then(() => window.dispatchEvent(new Event('hashchange'))).catch(() => {});
        }
        return response;
    };
    function setup() {
        dialog().addEventListener('cancel', event => event.preventDefault());
        document.getElementById('session-form').addEventListener('submit', async event => {
            event.preventDefault();
            const input = document.getElementById('session-token');
            const token = input.value; input.value = '';
            const status = document.getElementById('session-status');
            const submit = document.getElementById('session-submit'); submit.disabled = true;
            try {
                const response = await originalFetch('/api/v1/session', {method:'POST',
                    headers:{'Content-Type':'application/json'}, body:JSON.stringify({token})});
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Sign-in failed');
                dialog().close(); status.textContent = ''; pending = null;
                resolveLogin?.(true); resolveLogin = null;
            } catch (error) { status.textContent = error.message; input.focus(); }
            finally { submit.disabled = false; }
        });
        document.getElementById('sign-out').addEventListener('click', async () => {
            await originalFetch('/api/v1/session', {method:'DELETE'}); location.reload();
        });
    }
    window.VisionSession = {ready, setup};
})();
