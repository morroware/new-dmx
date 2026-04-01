const U = {
    esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; },
    fmtDate(d) { if (!d) return '-'; return new Date(d + (d.includes('T') ? '' : 'T00:00:00Z')).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); },
    fmtDateTime(d) { if (!d) return '-'; return new Date(d + (d.includes('T') ? '' : 'T00:00:00Z')).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); },
    timeAgo(d) { if (!d) return ''; const s = Math.floor((Date.now() - new Date(d+'Z').getTime()) / 1000); if (s < 60) return 'just now'; if (s < 3600) return Math.floor(s/60) + 'm ago'; if (s < 86400) return Math.floor(s/3600) + 'h ago'; return U.fmtDate(d); },
    debounce(fn, delay = 300) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), delay); }; },
    statusTag(s) {
        const m = { subscribed:'ok',active:'ok',sent:'info',published:'ok',unsubscribed:'er',bounced:'warn',draft:'gray',paused:'warn',scheduled:'acc',sending:'info',failed:'er',planned:'acc' };
        return `<span class="tag tag-${m[s]||'gray'}"><span class="sdot" style="background:var(--${m[s]==='ok'?'ok':m[s]==='er'?'err':m[s]==='warn'?'warn':m[s]==='info'?'info':'acc'})"></span> ${U.esc(s)}</span>`;
    },
    buildQuery(p) { return Object.entries(p).filter(([,v]) => v !== '' && v != null).map(([k,v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&'); },
    $(sel) { return document.querySelector(sel); },
    $$(sel) { return document.querySelectorAll(sel); },
    pagination(pg, onPage) {
        if (!pg || pg.total_pages <= 1) return '';
        const { page, total, total_pages, per_page } = pg;
        const start = (page-1)*per_page+1, end = Math.min(page*per_page, total);
        let btns = `<button ${page<=1?'disabled':''} data-p="${page-1}">&laquo;</button>`;
        for (let i = Math.max(1,page-2); i <= Math.min(total_pages,page+2); i++) btns += `<button class="${i===page?'on':''}" data-p="${i}">${i}</button>`;
        btns += `<button ${page>=total_pages?'disabled':''} data-p="${page+1}">&raquo;</button>`;
        return `<div class="pag"><div class="pag-info">${start}-${end} of ${total}</div><div class="pag-btns" data-pag>${btns}</div></div>`;
    },
    bindPag(el, fn) { const c = el.querySelector('[data-pag]'); if (c) c.onclick = e => { if (e.target.tagName === 'BUTTON' && !e.target.disabled) fn(+e.target.dataset.p); }; },
    async copy(text) { try { await navigator.clipboard.writeText(text); Toast.ok('Copied!'); } catch { Toast.ok('Copied!'); } },
    confirm(msg) { return window.confirm(msg); },
};

const Toast = {
    el: null,
    init() { this.el = document.getElementById('toasts'); if (!this.el) { this.el = document.createElement('div'); this.el.id = 'toasts'; document.body.appendChild(this.el); } },
    show(msg, type = 'info', dur = 4000) { if (!this.el) this.init(); const t = document.createElement('div'); t.className = `toast toast-${type}`; t.innerHTML = `<span>${U.esc(msg)}</span><button class="tx" onclick="this.parentElement.remove()">&times;</button>`; this.el.appendChild(t); setTimeout(() => t.remove(), dur); },
    ok(m) { this.show(m, 'ok'); }, err(m) { this.show(m, 'er', 6000); }, warn(m) { this.show(m, 'warn'); }, info(m) { this.show(m, 'info'); },
};

const Modal = {
    show(title, content, size = 'md', footer = '') {
        this.close();
        const bg = document.createElement('div'); bg.className = 'modal-bg'; bg.id = 'modal-bg';
        bg.innerHTML = `<div class="modal modal-${size}"><div class="modal-hd"><h3>${title}</h3><button class="modal-x" onclick="Modal.close()">&times;</button></div><div class="modal-bd">${content}</div>${footer ? `<div class="modal-ft">${footer}</div>` : ''}</div>`;
        document.body.appendChild(bg);
        bg.onclick = e => { if (e.target === bg) Modal.close(); };
        requestAnimationFrame(() => bg.classList.add('on'));
    },
    close() { const bg = document.getElementById('modal-bg'); if (bg) { bg.classList.remove('on'); setTimeout(() => bg.remove(), 200); } },
    body() { return document.querySelector('#modal-bg .modal-bd'); },
};
