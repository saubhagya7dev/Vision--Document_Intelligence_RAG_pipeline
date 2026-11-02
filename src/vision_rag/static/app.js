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
    const PAGES = ['dashboard', 'upload', 'chat', 'documents'];

    // Session state
    let queryCount = parseInt(sessionStorage.getItem('vr_query_count') || '0', 10);
    let chatHistory = JSON.parse(sessionStorage.getItem('vr_chat_history') || '[]');
    let lastSources = JSON.parse(sessionStorage.getItem('vr_last_sources') || '[]');
    let uploadHistory = JSON.parse(sessionStorage.getItem('vr_upload_history') || '[]');
    let activityLog = JSON.parse(sessionStorage.getItem('vr_activity') || '[]');

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

        uploadFile(file, onProgress) {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
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

                xhr.open('POST', `${API_BASE}/ingest`);
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

        getPageImageUrl(filename, pageNum, thumbnail = false) {
            return `${API_BASE}/documents/${encodeURIComponent(filename)}/pages/${pageNum}${thumbnail ? '?thumbnail=true' : ''}`;
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
                <button class="toast-dismiss" onclick="this.parentElement.classList.add('removing'); setTimeout(() => this.parentElement.remove(), 300)">×</button>
            `;

            container.appendChild(el);

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

    function parseMarkdown(text) {
        if (!text) return '';
        let html = escapeHtml(text);

        // Code blocks (```)
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        // Inline code
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        // Bold
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Italic
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        // Unordered lists
        html = html.replace(/^[\s]*[-•]\s+(.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
        // Ordered lists
        html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
        // Paragraphs (double newline)
        html = html.replace(/\n\n/g, '</p><p>');
        // Single newlines (within paragraphs)
        html = html.replace(/\n/g, '<br>');

        return `<p>${html}</p>`;
    }

    function saveSessionState() {
        sessionStorage.setItem('vr_query_count', queryCount.toString());
        sessionStorage.setItem('vr_chat_history', JSON.stringify(chatHistory));
        sessionStorage.setItem('vr_last_sources', JSON.stringify(lastSources));
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
        const hash = window.location.hash.replace('#', '') || 'dashboard';
        return PAGES.includes(hash) ? hash : 'dashboard';
    }

    function navigateTo(page) {
        // Hide all pages
        document.querySelectorAll('.page').forEach(p => {
            p.classList.remove('active');
        });

        // Show target page
        const target = document.getElementById(`page-${page}`);
        if (target) {
            target.classList.add('active');
        }

        // Update nav
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === page);
        });

        // Trigger page-specific init
        if (page === 'dashboard') initDashboard();
        if (page === 'documents') initDocuments();
        if (page === 'chat') initChat();
        if (page === 'upload') initUpload();
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
        // Update session query count
        document.getElementById('stat-queries-count').textContent = queryCount;

        // Render activity
        renderActivity();

        // Fetch live stats
        try {
            const stats = await api.get('/stats');
            document.getElementById('stat-doc-count').textContent = stats.total_documents || 0;
            document.getElementById('stat-pages-count').textContent = stats.total_vectors || 0;
            document.getElementById('hero-total-pages').textContent = stats.total_vectors || 0;

            const statusEl = document.getElementById('stat-system-status');
            const status = stats.collection_status || 'unknown';
            statusEl.textContent = status === 'green' || status === 'CollectionStatus.GREEN' ? 'Healthy' : status;
            statusEl.style.color = (status === 'green' || status === 'CollectionStatus.GREEN') ? '#10b981' : '#737373';
        } catch (e) {
            document.getElementById('stat-doc-count').textContent = '—';
            document.getElementById('stat-pages-count').textContent = '—';
            document.getElementById('stat-system-status').textContent = 'Error';
        }
    }

    function renderActivity() {
        const container = document.getElementById('activity-list');
        if (activityLog.length === 0) {
            container.innerHTML = '<div class="empty-state small"><p>No recent activity yet. Upload a document to get started.</p></div>';
            return;
        }

        container.innerHTML = activityLog.slice(0, 10).map(item => {
            const iconSvg = item.type === 'upload'
                ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>'
                : item.type === 'query'
                    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>'
                    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>';

            return `
                <div class="activity-item">
                    <div class="activity-icon">${iconSvg}</div>
                    <span class="activity-text">${escapeHtml(item.text)}</span>
                    <span class="activity-time">${timeAgo(item.time)}</span>
                </div>
            `;
        }).join('');
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

    async function handleFileUpload(file) {
        // Validate
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            toast.show('Only PDF files are supported.', 'error');
            return;
        }

        // Show progress UI
        const progressContainer = document.getElementById('upload-progress-container');
        const progressFill = document.getElementById('progress-fill');
        const filenameEl = document.getElementById('upload-filename');
        const filesizeEl = document.getElementById('upload-filesize');
        const statusEl = document.getElementById('upload-status');

        progressContainer.style.display = 'block';
        filenameEl.textContent = file.name;
        filesizeEl.textContent = formatBytes(file.size);
        progressFill.style.width = '0%';
        statusEl.textContent = 'Uploading...';

        try {
            await api.uploadFile(file, (percent) => {
                progressFill.style.width = `${percent}%`;
                statusEl.textContent = percent < 100 ? `Uploading... ${percent}%` : 'Processing document...';
            });

            progressFill.style.width = '100%';
            statusEl.textContent = 'Ingested successfully!';
            statusEl.style.color = '#10b981';

            // Add to upload history
            uploadHistory.unshift({
                name: file.name,
                size: file.size,
                time: new Date().toISOString(),
                status: 'success'
            });
            addActivity('upload', `Uploaded "${file.name}"`);
            saveSessionState();
            renderUploadHistory();

            toast.show(`Successfully ingested ${file.name}`, 'success');

            // Reset progress after delay
            setTimeout(() => {
                progressContainer.style.display = 'none';
                statusEl.style.color = '';
            }, 3000);

        } catch (err) {
            statusEl.textContent = `Error: ${err.message}`;
            statusEl.style.color = '#ef4444';

            uploadHistory.unshift({
                name: file.name,
                size: file.size,
                time: new Date().toISOString(),
                status: 'error'
            });
            saveSessionState();
            renderUploadHistory();

            toast.show(`Upload failed: ${err.message}`, 'error');
        }
    }

    function renderUploadHistory() {
        const container = document.getElementById('upload-history');
        if (uploadHistory.length === 0) {
            container.innerHTML = '<div class="empty-state small"><p>No documents uploaded in this session yet.</p></div>';
            return;
        }

        container.innerHTML = uploadHistory.map(item => `
            <div class="upload-history-item">
                <div class="file-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </div>
                <div class="file-details">
                    <div class="file-name">${escapeHtml(item.name)}</div>
                    <div class="file-meta">${formatBytes(item.size)} • ${timeAgo(item.time)}</div>
                </div>
                <span class="status-badge ${item.status}">${item.status === 'success' ? 'Ingested' : 'Failed'}</span>
            </div>
        `).join('');
    }

    // =========================
    // CHAT
    // =========================
    function initChat() {
        renderChatMessages();
        renderSources();

        // Focus input
        setTimeout(() => document.getElementById('chat-input').focus(), 100);
    }

    function setupChat() {
        const input = document.getElementById('chat-input');
        const sendBtn = document.getElementById('send-btn');
        const topkSlider = document.getElementById('topk-slider');
        const topkValue = document.getElementById('topk-value');
        const clearBtn = document.getElementById('clear-chat-btn');

        // Send on Enter
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendQuery();
            }
        });

        sendBtn.addEventListener('click', sendQuery);

        // Top-K slider
        topkSlider.addEventListener('input', () => {
            topkValue.textContent = topkSlider.value;
        });

        // Clear chat
        clearBtn.addEventListener('click', () => {
            chatHistory = [];
            lastSources = [];
            saveSessionState();
            renderChatMessages();
            renderSources();
        });
    }

    async function sendQuery() {
        const input = document.getElementById('chat-input');
        const sendBtn = document.getElementById('send-btn');
        const query = input.value.trim();

        if (!query) return;

        // Add user message
        chatHistory.push({ role: 'user', content: query });
        saveSessionState();
        renderChatMessages();

        // Clear input
        input.value = '';
        sendBtn.disabled = true;

        // Show typing indicator
        showTypingIndicator();

        const topK = parseInt(document.getElementById('topk-slider').value, 10);

        try {
            const result = await api.post('/query', { query, top_k: topK });

            // Remove typing indicator
            hideTypingIndicator();

            // Add AI response
            chatHistory.push({
                role: 'ai',
                content: result.answer,
                sources: result.sources
            });

            // Update sources
            lastSources = result.sources || [];

            // Track query
            queryCount++;
            addActivity('query', `Queried: "${query.substring(0, 50)}${query.length > 50 ? '...' : ''}"`);
            saveSessionState();

            renderChatMessages();
            renderSources();

            // Update dashboard query count if visible
            const qcEl = document.getElementById('stat-queries-count');
            if (qcEl) qcEl.textContent = queryCount;

        } catch (err) {
            hideTypingIndicator();

            chatHistory.push({
                role: 'ai',
                content: `Error: ${err.message}`,
                isError: true
            });
            saveSessionState();
            renderChatMessages();

            toast.show(`Query failed: ${err.message}`, 'error');
        }

        sendBtn.disabled = false;
        input.focus();
    }

    function showTypingIndicator() {
        const container = document.getElementById('chat-messages');
        const emptyState = document.getElementById('chat-empty');
        if (emptyState) emptyState.style.display = 'none';

        const indicator = document.createElement('div');
        indicator.id = 'typing-indicator';
        indicator.className = 'message ai';
        indicator.innerHTML = `
            <div class="message-bubble">
                <div class="message-label">
                    <span>✦</span> Vision RAG AI <span class="ai-dot"></span>
                </div>
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;
        container.appendChild(indicator);
        container.scrollTop = container.scrollHeight;
    }

    function hideTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) indicator.remove();
    }

    function renderChatMessages() {
        const container = document.getElementById('chat-messages');
        const emptyState = document.getElementById('chat-empty');

        if (chatHistory.length === 0) {
            // Reset: clear everything and re-add empty state
            container.innerHTML = '';
            if (emptyState) {
                emptyState.style.display = '';
                container.appendChild(emptyState);
            } else {
                container.innerHTML = `
                    <div class="chat-empty-state" id="chat-empty">
                        <div class="empty-icon">
                            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                        </div>
                        <h2>Ask your first question</h2>
                        <p>Query your uploaded documents using natural language. Vision RAG understands tables, charts, and diagrams.</p>
                    </div>
                `;
            }
            return;
        }

        // Remove empty state reference before rebuilding
        const existingEmpty = container.querySelector('#chat-empty');

        // Build messages HTML
        let html = '';
        chatHistory.forEach(msg => {
            if (msg.role === 'user') {
                html += `
                    <div class="message user">
                        <div class="message-bubble">${escapeHtml(msg.content)}</div>
                    </div>
                `;
            } else {
                const labelColor = msg.isError ? 'color: #ef4444' : '';
                html += `
                    <div class="message ai">
                        <div class="message-bubble" ${msg.isError ? 'style="border-color: rgba(239,68,68,0.3)"' : ''}>
                            <div class="message-label" style="${labelColor}">
                                <span>✦</span> Vision RAG AI <span class="ai-dot"></span>
                            </div>
                            ${parseMarkdown(msg.content)}
                        </div>
                    </div>
                `;
            }
        });

        container.innerHTML = html;

        // Scroll to bottom
        requestAnimationFrame(() => {
            container.scrollTop = container.scrollHeight;
        });
    }

    function renderSources() {
        const list = document.getElementById('source-list');
        const countEl = document.getElementById('source-count');

        if (!lastSources || lastSources.length === 0) {
            countEl.textContent = '0 pages';
            list.innerHTML = '<div class="empty-state small"><p>Source pages will appear here after querying.</p></div>';
            return;
        }

        countEl.textContent = `${lastSources.length} page${lastSources.length !== 1 ? 's' : ''}`;

        list.innerHTML = lastSources.map((src, i) => {
            const filename = src.source ? src.source.replace(/^.*[\\\/]/, '') : 'Unknown';
            const page = src.page || '?';
            const score = typeof src.score === 'number' ? src.score.toFixed(2) : '—';
            const imgUrl = src.source ? api.getPageImageUrl(filename, page, true) : '';

            return `
                <div class="source-card" data-src-index="${i}" onclick="window.__previewSource(${i})">
                    <div class="source-thumb">
                        ${imgUrl ? `<img src="${imgUrl}" alt="Page ${page}" loading="lazy" onerror="this.style.display='none'">` : ''}
                    </div>
                    <div class="source-info">
                        <div class="source-page-label">Page ${page}</div>
                        <div class="source-file-name" title="${escapeHtml(filename)}">${escapeHtml(filename)}</div>
                        <span class="source-score">Score: ${score}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Preview source page in modal
    window.__previewSource = function (index) {
        const src = lastSources[index];
        if (!src) return;

        const filename = src.source ? src.source.replace(/^.*[\\\/]/, '') : 'Unknown';
        const page = src.page || '?';
        const imgUrl = src.source ? api.getPageImageUrl(filename, page) : '';

        document.getElementById('preview-modal-title').textContent = `${filename} — Page ${page}`;
        document.getElementById('preview-image').src = imgUrl;
        document.getElementById('preview-modal').style.display = 'flex';
    };

    // =========================
    // DOCUMENTS
    // =========================
    async function initDocuments() {
        const grid = document.getElementById('documents-grid');
        const emptyState = document.getElementById('docs-empty-state');

        // Show loading skeleton
        grid.innerHTML = Array.from({ length: 3 }, () => `
            <div class="doc-card">
                <div class="doc-card-header">
                    <div class="skeleton" style="width: 44px; height: 44px;"></div>
                    <div class="doc-card-title" style="flex:1">
                        <div class="skeleton" style="height: 16px; width: 80%; margin-bottom: 6px;"></div>
                        <div class="skeleton" style="height: 12px; width: 50%;"></div>
                    </div>
                </div>
                <div class="doc-card-meta">
                    <div class="skeleton" style="height: 24px; width: 70px;"></div>
                    <div class="skeleton" style="height: 24px; width: 60px;"></div>
                </div>
            </div>
        `).join('');

        try {
            const docs = await api.get('/documents');

            if (!docs || docs.length === 0) {
                grid.innerHTML = '';
                grid.appendChild(createEmptyDocsState());
                return;
            }

            grid.innerHTML = docs.map(doc => `
                <div class="doc-card" data-filename="${escapeHtml(doc.filename)}">
                    <div class="doc-card-header">
                        <div class="doc-card-icon">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                        </div>
                        <div class="doc-card-title">
                            <div class="doc-card-name" title="${escapeHtml(doc.filename)}">${escapeHtml(doc.filename)}</div>
                            <div class="doc-card-date">${timeAgo(doc.uploaded_at)}</div>
                        </div>
                    </div>
                    <div class="doc-card-meta">
                        <span class="doc-meta-tag">${doc.page_count} page${doc.page_count !== 1 ? 's' : ''}</span>
                        <span class="doc-meta-tag">${formatBytes(doc.size_bytes)}</span>
                    </div>
                    <div class="doc-card-actions">
                        <button class="doc-delete-btn" onclick="window.__deleteDoc('${escapeHtml(doc.filename)}')">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                            Delete
                        </button>
                    </div>
                </div>
            `).join('');

        } catch (err) {
            grid.innerHTML = '';
            grid.appendChild(createEmptyDocsState());
            toast.show(`Failed to load documents: ${err.message}`, 'error');
        }
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

    window.__deleteDoc = function (filename) {
        pendingDeleteFilename = filename;
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
                addActivity('delete', `Deleted "${filename}"`);
                toast.show(`Deleted ${filename}`, 'success');
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
    function setupDashboardControls() {
        document.getElementById('refresh-stats-btn').addEventListener('click', () => {
            initDashboard();
            toast.show('Stats refreshed', 'info', 2000);
        });
    }

    // =========================
    // INITIALIZATION
    // =========================
    function init() {
        // Setup event listeners
        setupUpload();
        setupChat();
        setupDeleteModal();
        setupDashboardControls();

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

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
