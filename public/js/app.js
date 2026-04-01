/**
 * NEXUS - Main Application Shell
 */
const App = {
    user: null,
    page: null,

    async init() {
        Toast.init();
        try {
            const res = await API.get('/auth/me');
            if (res.user) { this.user = res.user; this.renderShell(); return; }
        } catch {}
        this.showLogin();
    },

    showLogin() {
        this.user = null;
        document.getElementById('app').innerHTML = `
        <div class="login-screen"><div class="login-card">
            <div class="text-center mb-2"><div style="display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;background:var(--acc);border-radius:10px;color:#fff;font-size:20px;font-weight:800;margin-bottom:8px">◆</div></div>
            <h1>NEXUS</h1><p class="sub">Marketing Platform · v3.0</p>
            <form id="login-form">
                <div class="fg"><label class="fl">Email</label><input type="email" class="fi" name="email" value="admin@nexus.local" required></div>
                <div class="fg"><label class="fl">Password</label><input type="password" class="fi" name="password" required placeholder="Set on first login"></div>
                <button type="submit" class="btn btn-p btn-lg btn-w">Sign In</button>
                <div id="login-err" class="text-center mt-1 hidden" style="color:var(--err);font-size:11px"></div>
            </form>
        </div></div>`;
        document.getElementById('login-form').onsubmit = async (e) => {
            e.preventDefault();
            try {
                const f = e.target;
                const res = await API.post('/auth/login', { email: f.email.value, password: f.password.value });
                this.user = res.user; this.renderShell();
            } catch (err) {
                const el = document.getElementById('login-err'); el.textContent = err.message; el.classList.remove('hidden');
            }
        };
    },

    renderShell() {
        const initials = (this.user.name || 'U').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
        document.getElementById('app').innerHTML = `
        <div class="shell">
            <aside class="side" id="sidebar">
                <div class="side-logo"><h1><em>◆</em> NEXUS</h1><p>Marketing Platform · $0/mo</p></div>
                <nav class="side-nav">
                    <div class="nl">Studio</div>
                    <div class="ni" data-p="studio"><div class="nii">✦</div> Content Studio</div>
                    <div class="ni" data-p="calendar"><div class="nii">📅</div> Calendar</div>
                    <div class="nl">Audience</div>
                    <div class="ni" data-p="contacts"><div class="nii">👤</div> Contacts</div>
                    <div class="ni" data-p="lists"><div class="nii">☰</div> Lists</div>
                    <div class="ni" data-p="tags"><div class="nii">🏷</div> Tags</div>
                    <div class="nl">Campaigns</div>
                    <div class="ni" data-p="campaigns"><div class="nii">✉</div> Email Campaigns</div>
                    <div class="ni" data-p="templates"><div class="nii">✎</div> Templates</div>
                    <div class="ni" data-p="automations"><div class="nii">⚡</div> Automations</div>
                    <div class="nl">Growth</div>
                    <div class="ni" data-p="forms"><div class="nii">☐</div> Forms</div>
                    <div class="ni" data-p="pages"><div class="nii">◫</div> Landing Pages</div>
                    <div class="nl">Analytics</div>
                    <div class="ni" data-p="dashboard"><div class="nii">◆</div> Dashboard</div>
                    <div class="ni" data-p="settings"><div class="nii">⚙</div> Settings</div>
                </nav>
                <div class="side-foot" id="conn-status">v3.0 · Direct APIs</div>
            </aside>
            <div class="main" id="main">
                <header class="hdr">
                    <div class="hdr-left"><button class="menu-btn" id="menu-btn">☰</button><div class="bc" id="bc"></div></div>
                    <div class="hdr-right">
                        <div class="usr" id="usr-menu"><div class="usr-av">${initials}</div><span style="font-size:12px">${U.esc(this.user.name)}</span><span style="font-size:9px;color:var(--t3)">▾</span></div>
                        <div class="dd-menu" id="usr-dd">
                            <div class="dd-item" onclick="App.nav('settings')">Settings</div>
                            <div class="dd-div"></div>
                            <div class="dd-item er" onclick="App.logout()">Sign Out</div>
                        </div>
                    </div>
                </header>
                <div class="content" id="content"><div class="loading"><div class="spin"></div></div></div>
            </div>
        </div>`;
        this.bind();
        this.route();
        window.onhashchange = () => this.route();
        this.loadConnections();
    },

    bind() {
        document.querySelectorAll('.ni[data-p]').forEach(el => el.onclick = () => { this.nav(el.dataset.p); document.getElementById('sidebar').classList.remove('open'); });
        document.getElementById('menu-btn').onclick = () => document.getElementById('sidebar').classList.toggle('open');
        document.getElementById('usr-menu').onclick = e => { e.stopPropagation(); document.getElementById('usr-dd').classList.toggle('show'); };
        document.onclick = () => document.querySelectorAll('.dd-menu.show').forEach(el => el.classList.remove('show'));
    },

    nav(page, id, sub) {
        let hash = '#/' + page;
        if (id) hash += '/' + id;
        if (sub) hash += '/' + sub;
        window.location.hash = hash;
    },

    route() {
        const hash = (window.location.hash || '#/studio').replace('#/', '');
        const [page, id, sub] = hash.split('/');
        document.querySelectorAll('.ni').forEach(el => el.classList.toggle('on', el.dataset.p === page));
        const names = { studio:'Content Studio',calendar:'Calendar',contacts:'Contacts',lists:'Lists',tags:'Tags',campaigns:'Email Campaigns',templates:'Templates',automations:'Automations',forms:'Forms',pages:'Landing Pages',dashboard:'Dashboard',settings:'Settings' };
        const bc = document.getElementById('bc');
        if (bc) bc.innerHTML = `<span>NEXUS</span> / <span>${names[page] || page}</span>`;
        this.page = page;
        this.loadPage(page, id, sub);
    },

    async loadPage(page, id, sub) {
        const el = document.getElementById('content');
        el.innerHTML = '<div class="loading"><div class="spin"></div></div>';
        try {
            switch (page) {
                case 'studio': await Pages.studio(el); break;
                case 'dashboard': await Pages.dashboard(el); break;
                case 'contacts': id ? await Pages.contactDetail(el, id) : await Pages.contacts(el); break;
                case 'lists': id ? await Pages.listDetail(el, id) : await Pages.lists(el); break;
                case 'tags': await Pages.tags(el); break;
                case 'campaigns': id === 'new' || sub === 'edit' ? await Pages.campaignEdit(el, id === 'new' ? null : id) : id ? await Pages.campaignDetail(el, id) : await Pages.campaigns(el); break;
                case 'templates': id ? await Pages.templateEdit(el, id) : await Pages.templates(el); break;
                case 'automations': id ? await Pages.automationEdit(el, id) : await Pages.automations(el); break;
                case 'forms': id ? await Pages.formEdit(el, id) : await Pages.forms(el); break;
                case 'pages': id ? await Pages.pageEdit(el, id) : await Pages.pages(el); break;
                case 'calendar': await Pages.calendar(el); break;
                case 'settings': await Pages.settings(el); break;
                default: el.innerHTML = '<div class="empty"><h3>Not Found</h3></div>';
            }
        } catch (err) {
            el.innerHTML = `<div class="empty"><h3>Error</h3><p>${U.esc(err.message)}</p></div>`;
        }
    },

    async loadConnections() {
        try {
            const c = await API.get('/studio/connections');
            const el = document.getElementById('conn-status');
            if (!el) return;
            let html = '<div style="padding:4px 0">';
            for (const [k, v] of Object.entries(c)) {
                const color = v.connected ? (k === 'facebook' ? '#1877F2' : k === 'instagram' ? '#E4405F' : k === 'tiktok' ? '#fff' : 'var(--ok)') : 'var(--t3)';
                html += `<div class="fr" style="padding:1px 0;font-size:9px;color:var(--t3)"><span class="sdot" style="background:${color}"></span><span>${v.name}</span></div>`;
            }
            html += '</div>';
            el.innerHTML = html;
        } catch {}
    },

    async logout() { await API.post('/auth/logout'); this.showLogin(); },
};

document.addEventListener('DOMContentLoaded', () => App.init());
