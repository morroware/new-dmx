/**
 * MarketFlow Utility Functions
 */

const Utils = {
    // Format numbers
    formatNumber(n) {
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
        return String(n);
    },

    // Format date
    formatDate(dateStr) {
        if (!dateStr) return '-';
        const d = new Date(dateStr + (dateStr.includes('T') ? '' : 'T00:00:00Z'));
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    },

    formatDateTime(dateStr) {
        if (!dateStr) return '-';
        const d = new Date(dateStr + (dateStr.includes('T') ? '' : 'T00:00:00Z'));
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    },

    timeAgo(dateStr) {
        if (!dateStr) return '';
        const now = new Date();
        const d = new Date(dateStr + (dateStr.includes('T') ? '' : 'T00:00:00Z'));
        const secs = Math.floor((now - d) / 1000);
        if (secs < 60) return 'just now';
        if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
        if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
        if (secs < 604800) return Math.floor(secs / 86400) + 'd ago';
        return Utils.formatDate(dateStr);
    },

    // Escape HTML
    esc(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    },

    // Debounce
    debounce(fn, delay = 300) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn(...args), delay);
        };
    },

    // Status badge
    statusBadge(status) {
        const map = {
            subscribed: 'success', active: 'success', sent: 'info', published: 'success',
            unsubscribed: 'danger', bounced: 'warning', complained: 'danger',
            draft: 'gray', paused: 'warning', scheduled: 'primary', sending: 'info',
            failed: 'danger',
        };
        const cls = map[status] || 'gray';
        return `<span class="tag tag-${cls}"><span class="status-dot ${status}"></span> ${Utils.esc(status)}</span>`;
    },

    // Build query string from object
    buildQuery(params) {
        return Object.entries(params)
            .filter(([, v]) => v !== '' && v !== null && v !== undefined)
            .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
            .join('&');
    },

    // Simple template
    $(selector) { return document.querySelector(selector); },
    $$(selector) { return document.querySelectorAll(selector); },

    // Create element from HTML string
    html(str) {
        const tpl = document.createElement('template');
        tpl.innerHTML = str.trim();
        return tpl.content.firstChild;
    },

    // Pagination helper
    renderPagination(pagination, onPageChange) {
        if (!pagination || pagination.total_pages <= 1) return '';
        const { page, total, total_pages, per_page } = pagination;
        const start = (page - 1) * per_page + 1;
        const end = Math.min(page * per_page, total);

        let buttons = '';
        buttons += `<button ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}">&laquo;</button>`;

        const startPage = Math.max(1, page - 2);
        const endPage = Math.min(total_pages, page + 2);
        for (let i = startPage; i <= endPage; i++) {
            buttons += `<button class="${i === page ? 'active' : ''}" data-page="${i}">${i}</button>`;
        }

        buttons += `<button ${page >= total_pages ? 'disabled' : ''} data-page="${page + 1}">&raquo;</button>`;

        return `<div class="pagination">
            <div class="pagination-info">Showing ${start}-${end} of ${total}</div>
            <div class="pagination-controls" data-pagination>${buttons}</div>
        </div>`;
    },

    bindPagination(container, onPageChange) {
        const ctrl = container.querySelector('[data-pagination]');
        if (ctrl) {
            ctrl.addEventListener('click', (e) => {
                if (e.target.tagName === 'BUTTON' && !e.target.disabled) {
                    onPageChange(parseInt(e.target.dataset.page));
                }
            });
        }
    },

    // Simple bar chart
    renderBarChart(container, data, labelKey, valueKey, color = 'var(--primary)') {
        if (!data || !data.length) {
            container.innerHTML = '<div class="empty-state"><p>No data available</p></div>';
            return;
        }
        const max = Math.max(...data.map(d => d[valueKey]));
        const barWidth = Math.max(4, Math.floor((container.clientWidth - 40) / data.length) - 2);

        let html = '<div style="position:relative;height:100%;padding:20px 20px 40px;">';
        data.forEach((d, i) => {
            const h = max > 0 ? (d[valueKey] / max) * 220 : 0;
            const left = 20 + i * (barWidth + 2);
            html += `<div class="chart-bar" style="left:${left}px;width:${barWidth}px;height:${h}px;background:${color}" title="${d[labelKey]}: ${d[valueKey]}"></div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    },

    // Confirm dialog
    confirm(message) {
        return window.confirm(message);
    },

    // Copy to clipboard
    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            Toast.success('Copied to clipboard');
        } catch {
            // Fallback
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            Toast.success('Copied to clipboard');
        }
    },
};

// Toast notifications
const Toast = {
    container: null,

    init() {
        this.container = document.getElementById('toast-container');
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'toast-container';
            document.body.appendChild(this.container);
        }
    },

    show(message, type = 'info', duration = 4000) {
        if (!this.container) this.init();
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `<span>${Utils.esc(message)}</span><button class="close-toast" onclick="this.parentElement.remove()">&times;</button>`;
        this.container.appendChild(toast);
        setTimeout(() => toast.remove(), duration);
    },

    success(msg) { this.show(msg, 'success'); },
    error(msg) { this.show(msg, 'error', 6000); },
    warning(msg) { this.show(msg, 'warning'); },
    info(msg) { this.show(msg, 'info'); },
};

// Modal helper
const Modal = {
    show(title, content, size = 'md', footer = '') {
        this.close();
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.id = 'modal-overlay';
        overlay.innerHTML = `
            <div class="modal modal-${size}">
                <div class="modal-header">
                    <h3>${title}</h3>
                    <button class="modal-close" onclick="Modal.close()">&times;</button>
                </div>
                <div class="modal-body">${content}</div>
                ${footer ? `<div class="modal-footer">${footer}</div>` : ''}
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) Modal.close();
        });
        requestAnimationFrame(() => overlay.classList.add('active'));
    },

    close() {
        const overlay = document.getElementById('modal-overlay');
        if (overlay) {
            overlay.classList.remove('active');
            setTimeout(() => overlay.remove(), 200);
        }
    },

    getBody() {
        return document.querySelector('#modal-overlay .modal-body');
    },
};
