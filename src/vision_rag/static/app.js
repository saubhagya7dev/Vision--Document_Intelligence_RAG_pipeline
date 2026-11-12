/* =====================================================
   VISION RAG — Application Logic
   SPA Router, API Client, Page Modules
   ===================================================== */

(() => {
    'use strict';

    // =========================
    // CONFIG
    // =========================
    const API_BASE = '/api/v1';
    const PAGES = ['dashboard', 'upload', 'chat', 'documents', 'analysis', 'findings'];

    // Session state
    let queryCount = parseInt(sessionStorage.getItem('vr_query_count') || '0', 10);
    let uploadHistory = JSON.parse(sessionStorage.getItem('vr_upload_history') || '[]');
    let activityLog = JSON.parse(sessionStorage.getItem('vr_activity') || '[]');
    let durableJobs = [];
    let jobsRefreshing = false;
    let activeUploadJobId = null;
    let activeUploadToken = null;
    let clearingData = false;
    const uploadRequests = new Set();
    const terminalJobs = new Set(['ready', 'failed', 'cancelled']);

    // =========================
    // API CLIENT
    // =========================
    const api = {
        async get(path) {
            const res = await fetch(`${API_BASE}${path}`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                throw new Error(err.detail || 'Request failed');
            }
            return res.json();
        },

        async post(path, body) {
            const res = await fetch(`${API_BASE}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                throw new Error(err.detail || 'Request failed');
            }
            return res.json();
        },

        async delete(path) {
            const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                throw new Error(err.detail || 'Request failed');
            }
            return res.json();
        },

        uploadFile(file, onProgress, documentId = null) {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                uploadRequests.add(xhr);
                xhr.addEventListener('loadend', () => uploadRequests.delete(xhr));
                const formData = new FormData();
                formData.append('file', file);

                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable && onProgress) {
                        onProgress(Math.round((e.loaded / e.total) * 100));
                    }
                });

                xhr.addEventListener('load', () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        resolve(JSON.parse(xhr.responseText));
                    } else {
                        try {
                            const err = JSON.parse(xhr.responseText);
                            reject(new Error(err.detail || 'Upload failed'));
                        } catch {
                            reject(new Error('Upload failed'));
                        }
                    }
                });

                xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
                xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));

                const path = documentId ? `/documents/${encodeURIComponent(documentId)}/versions` : '/ingest';
                xhr.open('POST', `${API_BASE}${path}`);
                xhr.send(formData);
            });
        },

        async healthCheck() {
            try {
                const res = await fetch('/health');
                return res.ok;
            } catch {
                return false;
            }
        },

        getPageImageUrl(filename, pageNum, thumbnail = false, versionId = null) {
            const source = versionId ? `/versions/${encodeURIComponent(versionId)}` : `/documents/${encodeURIComponent(filename)}`;
            return `${API_BASE}${source}/pages/${pageNum}${thumbnail ? '?thumbnail=true' : ''}`;
        }
    };

    // =========================
    // TOAST SYSTEM
    // =========================
    const toast = {
        show(message, type = 'info', duration = 4000) {
            const container = document.getElementById('toast-container');
            const el = document.createElement('div');
            el.className = `toast ${type}`;

            const iconSvg = type === 'success'
                ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>'
                : type === 'error'
                    ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
                    : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';

            el.innerHTML = `
                <span class="toast-icon">${iconSvg}</span>
                <span class="toast-message">${escapeHtml(message)}</span>
                <button class="toast-dismiss" aria-label="Dismiss notification">×</button>
            `;

            container.appendChild(el);
            el.querySelector('.toast-dismiss').addEventListener('click', () => el.remove());

            setTimeout(() => {
                if (el.parentElement) {
                    el.classList.add('removing');
                    setTimeout(() => el.remove(), 300);
                }
            }, duration);
        }
    };

    // =========================
    // UTILITIES
    // =========================
    function escapeHtml(str) {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return String(str).replace(/[&<>"']/g, c => map[c]);
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function timeAgo(isoString) {
        const date = new Date(isoString);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);
        if (diff < 60) return 'Just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return `${Math.floor(diff / 86400)}d ago`;
    }

    function saveSessionState() {
        if (clearingData) return;
        sessionStorage.setItem('vr_query_count', queryCount.toString());
        sessionStorage.setItem('vr_upload_history', JSON.stringify(uploadHistory));
        sessionStorage.setItem('vr_activity', JSON.stringify(activityLog));
    }

    function addActivity(type, text) {
        activityLog.unshift({ type, text, time: new Date().toISOString() });
        if (activityLog.length > 20) activityLog.pop();
        saveSessionState();
    }

    // =========================
    // ROUTER
    // =========================
    function getPageFromHash() {
        const hash = window.location.hash.replace('#', '') || 'chat';
        return PAGES.includes(hash) ? hash : 'chat';
    }

    function navigateTo(page) {
        // Hide all pages
        document.querySelectorAll('.page').forEach(p => {
            p.classList.remove('active');
        });

        // Show target page
        const target = document.getElementById(`page-${page === 'findings' ? 'analysis' : page}`);
        if (target) {
            target.classList.add('active');
        }

        // Update nav
        document.querySelectorAll('.nav-item').forEach(item => {
            const active = item.dataset.page === page;
            item.classList.toggle('active', active);
            if (active) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current');
        });

        document.getElementById(page === 'chat' ? 'chat-rail-footer' : 'workspace-utility-dock').append(document.getElementById('workspace-utilities'));
        document.body.dataset.findingsView = page === 'findings' ? 'saved' : 'compare';
        document.getElementById('analysis-title').textContent = page === 'findings' ? 'Saved findings' : 'Compare reports';
        window.dispatchEvent(new CustomEvent('vision-route-changed', {detail: page}));
        closeNavigation();
        // Trigger page-specific init
        if (page === 'dashboard') initDashboard();
        if (page === 'documents') initDocuments();
        if (page === 'chat') initChat();
        if (page === 'analysis' || page === 'findings') window.VisionFindings.open();
        if (page === 'upload') initUpload();
    }

    function closeNavigation() {
        document.querySelectorAll('#workspace-menu[open], .chat-actions[open]').forEach(menu => { menu.open = false; });
    }
    function setupNavigation() {
        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || document.querySelector('dialog[open]')) return;
            const menu = document.activeElement?.closest('details[open]');
            if (menu && menu.matches('#workspace-menu, .chat-actions')) {
                menu.open = false; menu.querySelector('summary').focus();
            }
        });
        document.getElementById('app-header').addEventListener('click', event => {
            if (event.target.closest('a, #data-controls-btn, #sign-out')) closeNavigation();
        });
        document.addEventListener('click', event => {
            if (event.target.closest('#data-controls-btn, #sign-out')) closeNavigation();
            document.querySelectorAll('#workspace-menu[open], .chat-actions[open]').forEach(menu => {
                if (!menu.contains(event.target)) menu.open = false;
            });
        });
    }

    // =========================
    // HEALTH CHECK
    // =========================
    async function checkHealth() {
        const statusEl = document.getElementById('api-status');
        const dotEl = statusEl.querySelector('.status-dot');
        const textEl = statusEl.querySelector('.status-text');

        try {
            const ok = await api.healthCheck();
            statusEl.className = `status-indicator ${ok ? 'online' : 'offline'}`;
            textEl.textContent = ok ? 'Online' : 'Offline';
        } catch {
            statusEl.className = 'status-indicator offline';
            textEl.textContent = 'Offline';
        }
    }

    // =========================
    // DASHBOARD
    // =========================
    async function initDashboard() {
        return window.VisionDashboard.refresh();
    }

    function renderActivity() {
        if (document.getElementById('page-dashboard').classList.contains('active')) window.VisionDashboard.refresh();
    }

    // =========================
    // UPLOAD
    // =========================
    function initUpload() {
        renderUploadHistory();
    }

    function setupUpload() {
        const zone = document.getElementById('upload-zone');
        const fileInput = document.getElementById('file-input');

        // Click to browse
        zone.addEventListener('click', () => fileInput.click());

        // Drag events
        ['dragenter', 'dragover'].forEach(event => {
            zone.addEventListener(event, (e) => {
                e.preventDefault();
                zone.classList.add('drag-over');
            });
        });
        ['dragleave', 'drop'].forEach(event => {
            zone.addEventListener(event, (e) => {
                e.preventDefault();
                zone.classList.remove('drag-over');
            });
        });

        zone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) handleFileUpload(files[0]);
        });

        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                handleFileUpload(fileInput.files[0]);
                fileInput.value = ''; // Reset
            }
        });
    }

    async function handleFileUpload(file, documentId = null) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            toast.show('Only PDF files are supported.', 'error');
            return;
        }
        const container = document.getElementById('upload-progress-container');
        const token = Symbol('upload');
        activeUploadToken = token;
        const fill = document.getElementById('progress-fill');
        const status = document.getElementById('upload-status');
        container.style.display = 'block';
        document.getElementById('upload-filename').textContent = file.name;
        document.getElementById('upload-filesize').textContent = formatBytes(file.size);
        fill.style.width = '0%';
        status.style.color = '';
        status.textContent = 'Uploading…';
        status.classList.add('luminous');
        activeUploadJobId = null;
        try {
            const job = await api.uploadFile(file, percent => {
                if (activeUploadToken !== token) return;
                fill.style.width = `${percent}%`;
                status.textContent = percent < 100 ? `Uploading... ${percent}%` : 'Validating upload...';
            }, documentId);
            if (activeUploadToken === token) {
                activeUploadJobId = job.id;
                fill.style.width = '0%';
                status.textContent = job.deduplicated ? 'Existing upload found; checking its job.' : 'Upload saved. Queued for indexing.';
            }
            toast.show(job.deduplicated ? 'This content is already in the library.' : 'Upload saved; indexing is queued.', 'info');
            await refreshJobs();
            window.dispatchEvent(new Event('vision-library-changed'));
            return job;
        } catch (error) {
            if (activeUploadToken === token) {
                status.classList.remove('luminous');
                status.textContent = `Upload failed: ${error.message}`;
                status.style.color = '#ef4444';
            }
            toast.show(`Upload failed: ${error.message}`, 'error');
        }
    }

    function jobLabel(job) {
        if (job.document_deleted && job.kind === 'ingest' && terminalJobs.has(job.state)) return 'Document removed';
        if (job.cancel_requested && !terminalJobs.has(job.state)) return 'Cancellation requested — finishing current batch';
        const labels = {
            uploaded: 'Queued', validating: 'Validating',
            loading_model: 'Loading embedding model', rendering: 'Rendering pages',
            embedding: 'Embedding pages', indexing: 'Saving index',
            extracting: 'Extracting text and checking layout', ocr: 'Reading scanned text',
            cleaning: 'Removing vectors and files',
            ready: job.kind === 'delete' ? 'Cleanup complete' : 'Ready',
            failed: 'Failed', cancelled: 'Cancelled'
        };
        return labels[job.state] || job.state;
    }

    function jobButtons(job) {
        if (job.document_deleted && job.kind === 'ingest') return '';
        if (['failed', 'cancelled'].includes(job.state)) {
            return `<button class="job-action" data-job-id="${escapeHtml(job.id)}" data-job-action="retry">Retry${job.kind === 'delete' ? ' cleanup' : ''}</button>`;
        }
        if (job.kind === 'ingest' && !terminalJobs.has(job.state) && !job.cancel_requested) {
            return `<button class="job-action" data-job-id="${escapeHtml(job.id)}" data-job-action="cancel">Cancel</button>`;
        }
        return '';
    }

    async function refreshJobs() {
        if (jobsRefreshing) return;
        jobsRefreshing = true;
        const connection = document.getElementById('jobs-connection');
        try {
            const jobs = await api.get('/jobs');
            const previous = new Map(durableJobs.map(job => [job.id, job.state]));
            durableJobs = jobs;
            window.dispatchEvent(new CustomEvent('vision-jobs-updated', {detail: jobs}));
            if (connection) connection.textContent = 'Recent jobs saved on the server';
            renderUploadHistory();
            let refreshDocuments = false;
            for (const job of jobs) {
                if (previous.has(job.id) && previous.get(job.id) !== job.state) {
                    if (job.state === 'ready') toast.show(`${job.filename}: ${jobLabel(job)}`, 'success');
                    if (job.state === 'failed') toast.show(`${job.filename}: processing failed. Retry is available.`, 'error');
                    if (terminalJobs.has(job.state)) refreshDocuments = true;
                }
                document.querySelectorAll('[data-document-job]').forEach(card => {
                    if (card.dataset.documentJob !== job.id) return;
                    card.querySelector('.doc-job-status').textContent = `${jobLabel(job)} · ${job.pages_done}/${job.total_pages} pages indexed${job.error ? ' · ' + job.error : ''}`;
                    card.querySelector('[data-job-buttons]').innerHTML = jobButtons(job);
                });
                if (job.id === activeUploadJobId) {
                    const percent = job.total_pages ? Math.round(100 * job.pages_done / job.total_pages) : 0;
                    document.getElementById('progress-fill').style.width = `${percent}%`;
                    document.getElementById('upload-status').classList.toggle('luminous', !terminalJobs.has(job.state));
                    document.getElementById('upload-status').textContent =
                        `${jobLabel(job)} — ${job.pages_done}/${job.total_pages} pages indexed${job.error ? '. ' + job.error : ''}`;
                }
            }
            if (refreshDocuments && getPageFromHash() === 'documents') await initDocuments();
        } catch (error) {
            if (connection) connection.textContent = 'Cannot refresh jobs. Retrying automatically.';
        } finally {
            jobsRefreshing = false;
        }
    }

    function renderUploadHistory() {
        const container = document.getElementById('upload-history');
        if (!durableJobs.length) {
            container.innerHTML = '<div class="empty-state small"><p>No ingestion or cleanup jobs yet.</p></div>';
            return;
        }
        container.innerHTML = durableJobs.map(job => {
            const style = job.state === 'ready' ? 'success' : job.state === 'failed' ? 'error' : 'processing';
            const label = escapeHtml(jobLabel(job));
            return `<div class="upload-history-item">
                <div class="file-details">
                    <div class="file-name">${escapeHtml(job.filename || 'Document')} ${job.kind === 'delete' ? '— deletion cleanup' : ''}</div>
                    <div class="file-meta">${label} ${job.kind === 'ingest' ? `· ${job.pages_done}/${job.total_pages} pages indexed` : ''} · attempt ${job.attempts}</div>
                    ${job.kind === 'ingest' ? `<progress max="${Math.max(1, job.total_pages)}" value="${job.pages_done}" aria-label="Indexed pages"></progress>` : ''}
                    ${job.error ? `<p class="job-error">${escapeHtml(job.error)}</p>` : ''}
                </div>
                <span class="status-badge ${style}${terminalJobs.has(job.state) ? '' : ' luminous'}">${label}</span>
                ${jobButtons(job)}
            </div>`;
        }).join('');
    }

    function setupJobActions() {
        setupProcessingControls();
        setupIndexControls();
        document.addEventListener('click', async event => {
            const button = event.target.closest('[data-job-action]');
            if (!button) return;
            button.disabled = true;
            try {
                await api.post(`/jobs/${encodeURIComponent(button.dataset.jobId)}/${button.dataset.jobAction}`, {});
                await refreshJobs();
                if (getPageFromHash() === 'documents') await initDocuments();
            } catch (error) {
                toast.show(error.message, 'error');
            } finally {
                button.disabled = false;
            }
        });
        document.addEventListener('click', event => {
            const chatDocument = event.target.closest('[data-chat-document]');
            if (chatDocument) { window.VisionWorkspace.useDocument(chatDocument.dataset.chatDocument); return; }
            const history = event.target.closest('[data-document-versions]');
            if (history) { showVersions(history.dataset.documentVersions); return; }
            const deletion = event.target.closest('[data-doc-delete]');
            if (deletion) {
                window.__deleteDoc(deletion.dataset.docDelete, deletion.dataset.filename);
                return;
            }
            const version = event.target.closest('[data-version-for]');
            if (version) {
                const picker = document.createElement('input');
                picker.type = 'file';
                picker.accept = '.pdf,application/pdf';
                picker.addEventListener('change', () => {
                    if (picker.files[0]) {
                        location.hash = '#upload';
                        handleFileUpload(picker.files[0], version.dataset.versionFor);
                    }
                });
                picker.click();
            }
        });
        refreshJobs();
        setInterval(() => {
            if (!document.hidden) refreshJobs();
        }, 2000);
    }

    // =========================
    // CHAT
    // =========================
    function setupIndexControls() {
        const panel = document.getElementById('retrieval-index-panel');
        const status = document.getElementById('retrieval-index-status');
        const list = document.getElementById('retrieval-index-list');
        const rebuild = document.getElementById('rebuild-index-btn');
        let refreshing = false;
        const refresh = async () => {
            if (refreshing) return;
            refreshing = true;
            try {
                const data = await api.get('/indexes');
                panel.hidden = false;
                const pending = data.indexes.some(index => ['queued', 'building'].includes(index.state));
                rebuild.disabled = pending;
                status.textContent = data.active ? (pending ? 'Updating retrieval. The current index stays active.' : 'Retrieval index ready.') : 'Preparing retrieval. You can ask questions after the index is ready.';
                list.innerHTML = data.indexes.slice(0, 8).map(index => `<div class="upload-history-item">
                    <div class="file-details"><div class="file-name">${index.id === data.active ? 'Active index' : 'Saved index'} · ${escapeHtml(index.state)}</div>
                    <div class="file-meta">${index.pages_done} pages processed · ${timeAgo(index.created_at)}</div>
                    ${index.error ? `<p class="job-error">${escapeHtml(index.error)}</p>` : ''}</div>
                    ${index.can_activate && index.id !== data.active ? `<button class="job-action" data-index-id="${escapeHtml(index.id)}" data-index-action="activate">Use this index</button>` : ''}
                    ${['queued', 'building'].includes(index.state) ? `<button class="job-action" data-index-id="${escapeHtml(index.id)}" data-index-action="cancel">Cancel build</button>` : ''}
                </div>`).join('');
            } catch (err) { status.textContent = `Index status unavailable: ${err.message}`; }
            finally { refreshing = false; }
        };
        rebuild.addEventListener('click', async () => {
            rebuild.disabled = true;
            try { await api.post('/indexes', {activate_when_ready: true}); await refresh(); }
            catch (err) { toast.show(err.message, 'error'); rebuild.disabled = false; }
        });
        document.addEventListener('click', async event => {
            const button = event.target.closest('[data-index-action]');
            if (!button) return;
            button.disabled = true;
            try { await api.post(`/indexes/${encodeURIComponent(button.dataset.indexId)}/${button.dataset.indexAction}`, {}); await refresh(); }
            catch (err) { toast.show(err.message, 'error'); button.disabled = false; }
        });
        refresh();
        setInterval(() => { if (!document.hidden) refresh(); }, 3000);
    }

    let processingVersion = null;
    let processingTimer = null;
    let processingGeneration = 0;

    function setupProcessingControls() {
        const dialog = document.getElementById('processing-dialog');
        const status = document.getElementById('processing-status');
        const pageInput = document.getElementById('processing-page');
        const submit = document.getElementById('processing-submit');
        const inspect = async () => {
            const version = processingVersion;
            const page = Number(pageInput.value);
            const generation = ++processingGeneration;
            submit.disabled = false;
            status.textContent = 'Loading page extraction…';
            for (const id of ['processing-text', 'processing-reasons', 'processing-warnings']) document.getElementById(id).textContent = '';
            try {
                const record = await api.get(`/versions/${encodeURIComponent(version)}/pages/${page}/text`);
                if (generation !== processingGeneration || !dialog.open) return;
                status.textContent = `Page ${page} · ${record.state} · revision ${record.revision} · ${record.mode}`;
                const data = record.data;
                document.getElementById('processing-mode').value = record.mode;
                document.getElementById('processing-reasons').textContent = `Text quality: ${data.quality || 'pending'}. ${(data.reasons || []).join(', ')}. Chunks: ${data.chunk_count || 0}.`;
                document.getElementById('processing-warnings').textContent = (data.warnings || []).join('; ');
                document.getElementById('processing-text').textContent = (data.native_text || '[No native text]') + (data.features?.ocr_text ? '\n\nOCR text:\n' + data.features.ocr_text : '');
                if (record.task && ['uploaded', 'running'].includes(record.task.state)) {
                    status.textContent += ` · task ${record.task.state}`;
                    submit.disabled = true;
                    processingTimer = setTimeout(inspect, 1500);
                } else if (record.task?.error) {
                    status.textContent += ` · ${record.task.error}`;
                }
            } catch (err) {
                if (generation === processingGeneration) status.textContent = `No extraction available: ${err.message}`;
            }
        };
        document.addEventListener('click', event => {
            const button = event.target.closest('[data-processing-version]');
            if (!button) return;
            processingVersion = button.dataset.processingVersion;
            pageInput.value = 1;
            document.getElementById('processing-mode').value = 'auto';
            dialog.showModal();
            inspect();
        });
        document.getElementById('processing-close').addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => {
            clearTimeout(processingTimer);
            processingGeneration++;
            submit.disabled = false;
        });
        document.getElementById('processing-inspect').addEventListener('click', inspect);
        submit.addEventListener('click', async () => {
            if (!pageInput.reportValidity()) return;
            submit.disabled = true;
            const generation = ++processingGeneration;
            try {
                const task = await api.post(`/versions/${encodeURIComponent(processingVersion)}/pages/${Number(pageInput.value)}/processing`, {mode: document.getElementById('processing-mode').value});
                const poll = async () => {
                    if (!dialog.open || generation !== processingGeneration) return;
                    try {
                        const saved = await api.get(`/page-tasks/${encodeURIComponent(task.id)}`);
                        if (!dialog.open || generation !== processingGeneration) return;
                        status.textContent = `Page ${saved.page_number}: ${saved.state} · attempt ${saved.attempts}${saved.error ? ' · ' + saved.error : ''}`;
                        if (['ready', 'failed', 'cancelled'].includes(saved.state)) {
                            submit.disabled = false;
                            if (saved.state === 'ready') await inspect();
                            return;
                        }
                    } catch (err) { status.textContent = `Connection lost: ${err.message}. Retrying…`; }
                    processingTimer = setTimeout(poll, 1500);
                };
                await poll();
            } catch (err) {
                status.textContent = err.message;
                submit.disabled = false;
            }
        });
    }

    function initChat() { window.VisionWorkspace.open(); }
    function setupChat() { window.VisionWorkspace.setup(); }

    // =========================
    // DOCUMENTS
    // =========================
    let libraryDocuments = [], libraryLoading = false;
    async function initDocuments(quiet = false) {
        if (libraryLoading) return;
        libraryLoading = true;
        const grid = document.getElementById('documents-grid');
        if (!quiet) grid.innerHTML = '<p class="library-empty luminous">Loading your documents…</p>';
        try {
            const readiness = await api.get('/workspace/readiness');
            libraryDocuments = readiness.documents;
            // Do not replace a menu or keyboard target while somebody is using it.
            if (!quiet || (!grid.contains(document.activeElement) && !grid.querySelector('details[open]'))) renderDocuments();
        } catch (error) {
            if (!quiet) {
                grid.replaceChildren();
                const p = document.createElement('p'); p.className = 'library-empty'; p.textContent = `Library unavailable: ${error.message}. Your documents have not been removed.`;
                const retry = document.createElement('button'); retry.className = 'job-action'; retry.textContent = 'Retry loading library';
                retry.addEventListener('click', () => initDocuments()); grid.append(p, retry);
            }
        } finally { libraryLoading = false; }
    }
    function renderDocuments() {
        const grid = document.getElementById('documents-grid');
        const search = document.getElementById('library-search').value.trim().toLocaleLowerCase();
        const filter = document.getElementById('library-filter').value;
        const docs = libraryDocuments.filter(doc => doc.filename.toLocaleLowerCase().includes(search) &&
            (filter === 'all' || (filter === 'ready' && doc.search_state === 'ready') ||
             (filter === 'processing' && ['reading', 'preparing'].includes(doc.search_state)) ||
             (filter === 'failed' && ['failed', 'empty'].includes(doc.search_state))));
        if (!libraryDocuments.length) { grid.replaceChildren(createEmptyDocsState()); return; }
        const scroll = grid.scrollLeft;
        const labels = {ready: 'Ready to ask', reading: 'Reading pages', preparing: 'Preparing search', failed: 'Preparation stopped', empty: 'No searchable pages'};
        grid.innerHTML = `<table class="library-table"><thead><tr><th scope="col">Document</th><th scope="col">Version</th><th scope="col">Pages</th><th scope="col">Status</th><th scope="col">Updated</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>${docs.map(doc => `
            <tr data-document-job="${escapeHtml(doc.job_id || '')}" data-filename="${escapeHtml(doc.filename)}">
                <td><div class="doc-card-name">▤ &nbsp;${escapeHtml(doc.filename)}</div><p class="doc-job-status">${doc.search_state === 'ready' ? `${doc.searchable_pages} searchable page${doc.searchable_pages === 1 ? '' : 's'}` : `${doc.pages_done || 0}/${doc.total_pages || doc.page_count} pages processed`}${doc.error ? ' · ' + escapeHtml(doc.error) : ''}</p>${doc.active_version_id && doc.active_version_id !== doc.version_id ? '<small>Previous version retained</small>' : ''}</td>
                <td>v${doc.version || '?'}</td><td>${doc.page_count}</td>
                <td><span class="library-state${['reading', 'preparing'].includes(doc.search_state) ? ' luminous' : ''}">${escapeHtml(labels[doc.search_state] || 'Check preparation')}</span></td>
                <td><span class="doc-card-date">${timeAgo(doc.uploaded_at)}</span></td>
                <td><details class="library-row-actions"><summary aria-label="Actions for ${escapeHtml(doc.filename)}">•••</summary><div>
                    <button class="job-action" data-chat-document="${escapeHtml(doc.id)}">Ask about this</button>
                    ${doc.active_version_id ? `<a class="job-action" href="/api/v1/versions/${encodeURIComponent(doc.active_version_id)}/file" target="_blank" rel="noopener">Original PDF ↗</a>` : ''}
                    <button class="job-action" data-document-versions="${escapeHtml(doc.id)}">Version history</button>
                    <span data-job-buttons>${doc.job_id ? jobButtons({id: doc.job_id, kind: 'ingest', state: doc.state, cancel_requested: doc.cancel_requested}) : ''}</span>
                    <button class="job-action" data-version-for="${escapeHtml(doc.id)}">New version</button>
                    ${doc.active_version_id ? `<button class="job-action" data-processing-version="${escapeHtml(doc.active_version_id)}">Page processing</button>` : ''}
                    <button class="doc-delete-btn" data-doc-delete="${escapeHtml(doc.id)}" data-filename="${escapeHtml(doc.filename)}">Delete document</button>
                </div></details></td>
            </tr>`).join('') || '<tr><td colspan="6" class="library-empty">No documents match this search and status.</td></tr>'}</tbody></table>`;
        grid.scrollLeft = scroll;
    }

    async function showVersions(id) {
        const dialog = document.getElementById('versions-dialog'), list = document.getElementById('versions-list');
        list.textContent = 'Loading document versions…'; dialog.showModal();
        try {
            const versions = await api.get(`/documents/${encodeURIComponent(id)}/versions`);
            list.replaceChildren();
            for (const version of versions) {
                const row = document.createElement('div'); row.className = 'version-row';
                const label = document.createElement('p'); label.textContent = `${version.filename} · Version ${version.ordinal} · ${version.state}`;
                row.append(label);
                const link = document.createElement('a'); link.className = 'quiet-action';
                link.href = `/api/v1/versions/${encodeURIComponent(version.id)}/file`; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Open original PDF ↗';
                row.append(link); list.append(row);
            }
        } catch (error) { list.textContent = `Version history unavailable: ${error.message}`; }
    }

    function createEmptyDocsState() {
        const el = document.createElement('div');
        el.className = 'empty-state';
        el.id = 'docs-empty-state';
        el.innerHTML = `
            <div class="empty-icon">
                <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <h2>No documents yet</h2>
            <p>Upload your first PDF to get started.</p>
            <a href="#upload" class="btn btn-primary">Upload Document</a>
        `;
        return el;
    }

    // Delete document
    let pendingDeleteFilename = null;

    window.__deleteDoc = function (reference, filename = reference) {
        pendingDeleteFilename = reference;
        document.getElementById('delete-modal-text').textContent = `Are you sure you want to delete "${filename}"? This will also remove its vectors from the database. This action cannot be undone.`;
        document.getElementById('delete-modal').style.display = 'flex';
    };

    function setupDeleteModal() {
        document.getElementById('delete-cancel-btn').addEventListener('click', () => {
            document.getElementById('delete-modal').style.display = 'none';
            pendingDeleteFilename = null;
        });

        document.getElementById('delete-confirm-btn').addEventListener('click', async () => {
            if (!pendingDeleteFilename) return;

            const filename = pendingDeleteFilename;
            document.getElementById('delete-modal').style.display = 'none';

            try {
                await api.delete(`/documents/${encodeURIComponent(filename)}`);
                addActivity('delete', 'Removed a document from the library');
                toast.show('Document removed; cleanup queued.', 'success');
                refreshJobs();
                initDocuments(); // Refresh list
            } catch (err) {
                toast.show(`Failed to delete: ${err.message}`, 'error');
            }

            pendingDeleteFilename = null;
        });

        // Close modals on overlay click
        document.querySelectorAll('.modal-overlay').forEach(overlay => {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    overlay.style.display = 'none';
                }
            });
        });

        // Preview modal close
        document.getElementById('preview-close-btn').addEventListener('click', () => {
            document.getElementById('preview-modal').style.display = 'none';
        });
    }

    // =========================
    // REFRESH STATS BUTTON
    // =========================
    function setupDataControls() {
        let pending = false;
        const dialog = document.getElementById('data-dialog');
        const status = document.getElementById('data-status');
        const submit = document.getElementById('data-submit');
        const close = document.getElementById('data-close');
        const confirmation = document.getElementById('data-confirm');
        const labels = {history: 'Clear history', cache: 'Clear page cache', reset: 'Delete library and start fresh'};
        const selected = () => dialog.querySelector('input[name="data-action"]:checked').value;
        const update = () => {
            const action = selected();
            document.getElementById('data-confirm-label').hidden = action !== 'reset';
            submit.textContent = labels[action];
            submit.disabled = action === 'reset' && confirmation.value !== 'DELETE';
            document.getElementById('data-description').textContent = action === 'reset'
                ? 'This permanently deletes library data. Running work will stop at its next safe boundary; an active model call may need time to finish.'
                : action === 'cache' ? 'Only derived page images and thumbnails are removed. Running ingestion may pause briefly.'
                : 'Chats and draft comparisons are cleared. Saved findings, documents and active jobs stay available. Browser history is cleared across open tabs of this app.';
        };
        const clearBrowserHistory = () => {
            for (const storage of [sessionStorage, localStorage]) {
                for (const key of Object.keys(storage)) {
                    if (key.startsWith('vr_') && key !== 'vr_reset_epoch') storage.removeItem(key);
                }
            }
            activityLog = []; uploadHistory = []; queryCount = 0;
        };
        window.addEventListener('storage', event => {
            if (event.key === 'vr_reset_epoch' && event.newValue) {
                clearingData = true;
                clearBrowserHistory();
                location.reload();
            }
        });
        document.getElementById('data-controls-btn').addEventListener('click', async () => {
            confirmation.value = '';
            status.textContent = '';
            update();
            dialog.showModal();
            try {
                const saved = await api.get('/maintenance');
                if (saved.reset_pending) status.textContent = 'A previous reset is incomplete. Select Start fresh and retry to finish cleanup.';
            } catch (err) { status.textContent = err.message; }
        });
        close.addEventListener('click', () => dialog.close());
        dialog.addEventListener('cancel', event => { if (pending) event.preventDefault(); });
        dialog.querySelectorAll('input[name="data-action"]').forEach(input => input.addEventListener('change', update));
        confirmation.addEventListener('input', update);
        submit.addEventListener('click', async () => {
            const action = selected();
            if (action === 'reset' && confirmation.value !== 'DELETE') return;
            pending = true;
            clearingData = action !== 'cache';
            if (action === 'reset') for (const upload of uploadRequests) upload.abort();
            submit.disabled = close.disabled = true;
            document.getElementById('data-options').disabled = true;
            status.textContent = 'Clearing data… Please wait for the server to finish.';
            try {
                await api.post('/maintenance', {action, confirmation: action === 'reset' ? 'DELETE' : 'CLEAR'});
                if (action === 'cache') {
                    pending = false;
                    close.disabled = false;
                    document.getElementById('data-options').disabled = false;
                    update();
                    status.textContent = 'Page cache cleared. Previews will regenerate when opened.';
                    return;
                }
                if (action !== 'cache') {
                    clearBrowserHistory();
                    localStorage.setItem('vr_reset_epoch', String(Date.now()));
                }
                // A new document prevents an old in-flight response restoring
                // cleared browser state and fetches the versioned current assets.
                location.replace('/?fresh=' + Date.now() + '#chat');
            } catch (err) {
                pending = false;
                clearingData = false;
                close.disabled = false;
                document.getElementById('data-options').disabled = false;
                status.textContent = err.message;
                update();
            }
        });
    }

    function setupDashboardControls() {
        window.VisionDashboard.setup();
    }

    // =========================
    // INITIALIZATION
    // =========================
    async function init() {
        window.VisionSession.setup();
        try { await window.VisionSession.ready(); }
        catch { document.getElementById('api-status').textContent = 'Offline — reload after reconnecting'; return; }
        // Setup event listeners
        document.getElementById('close-versions').addEventListener('click', () => document.getElementById('versions-dialog').close());
        document.getElementById('library-search').addEventListener('input', renderDocuments);
        document.getElementById('library-filter').addEventListener('change', renderDocuments);
        setInterval(() => { if (!document.hidden && getPageFromHash() === 'documents') initDocuments(true); }, 5000);
        setupNavigation();
        setupUpload();
        setupChat();
        window.VisionFindings.setup();
        setupDeleteModal();
        setupDashboardControls();
        setupJobActions();
        setupDataControls();

        // Router
        window.addEventListener('hashchange', () => {
            navigateTo(getPageFromHash());
        });

        // Initial navigation
        navigateTo(getPageFromHash());

        // Health check
        checkHealth();
        setInterval(checkHealth, 30000); // Check every 30 seconds
    }

    window.VisionUploads = {
        async upload(file, progress) {
            const job = await api.uploadFile(file, progress);
            await refreshJobs();
            window.dispatchEvent(new Event('vision-library-changed'));
            return job;
        },
    };

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
