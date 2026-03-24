/**
 * MarketFlow - Main Application
 * Vanilla JS SPA with hash-based routing
 */

const App = {
    user: null,
    currentPage: null,

    async init() {
        Toast.init();

        // Check auth
        try {
            const res = await API.me();
            if (res.user) {
                this.user = res.user;
                this.renderApp();
                this.bindEvents();
                this.handleRoute();
                window.addEventListener('hashchange', () => this.handleRoute());
                return;
            }
        } catch (e) {}

        this.showLogin();
    },

    showLogin() {
        this.user = null;
        document.getElementById('app').innerHTML = `
            <div id="login-screen">
                <div class="login-card">
                    <div class="text-center mb-3">
                        <div style="display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;background:var(--primary);border-radius:12px;color:#fff;font-size:24px;font-weight:800;margin-bottom:12px;">M</div>
                    </div>
                    <h1>MarketFlow</h1>
                    <p>Marketing Automation Platform</p>
                    <form id="login-form">
                        <div class="form-group">
                            <label class="form-label">Email</label>
                            <input type="email" class="form-input" name="email" value="admin@example.com" required autofocus>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Password</label>
                            <input type="password" class="form-input" name="password" required placeholder="Set password on first login">
                        </div>
                        <button type="submit" class="btn btn-primary btn-lg w-full">Sign In</button>
                        <div id="login-error" class="text-center mt-1 hidden" style="color:var(--danger);font-size:13px;"></div>
                    </form>
                </div>
            </div>
        `;
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const email = form.email.value;
            const password = form.password.value;
            try {
                const res = await API.login(email, password);
                this.user = res.user;
                this.renderApp();
                this.bindEvents();
                this.handleRoute();
                window.addEventListener('hashchange', () => this.handleRoute());
            } catch (err) {
                const errEl = document.getElementById('login-error');
                errEl.textContent = err.message;
                errEl.classList.remove('hidden');
            }
        });
    },

    renderApp() {
        const initials = (this.user.name || 'U').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
        document.getElementById('app').innerHTML = `
            <nav id="sidebar">
                <div class="sidebar-header">
                    <div class="logo">M</div>
                    <h2>MarketFlow</h2>
                </div>
                <div class="sidebar-nav">
                    <div class="nav-section">Main</div>
                    <div class="nav-item" data-page="dashboard"><span class="icon">&#9632;</span> Dashboard</div>

                    <div class="nav-section">Audience</div>
                    <div class="nav-item" data-page="contacts"><span class="icon">&#9786;</span> Contacts</div>
                    <div class="nav-item" data-page="lists"><span class="icon">&#9776;</span> Lists &amp; Segments</div>
                    <div class="nav-item" data-page="tags"><span class="icon">&#9873;</span> Tags</div>

                    <div class="nav-section">Messaging</div>
                    <div class="nav-item" data-page="campaigns"><span class="icon">&#9993;</span> Campaigns</div>
                    <div class="nav-item" data-page="templates"><span class="icon">&#9998;</span> Templates</div>
                    <div class="nav-item" data-page="automations"><span class="icon">&#9881;</span> Automations</div>

                    <div class="nav-section">Growth</div>
                    <div class="nav-item" data-page="forms"><span class="icon">&#9744;</span> Forms</div>
                    <div class="nav-item" data-page="pages"><span class="icon">&#9783;</span> Landing Pages</div>

                    <div class="nav-section">System</div>
                    <div class="nav-item" data-page="settings"><span class="icon">&#9881;</span> Settings</div>
                </div>
                <div class="sidebar-footer">v1.0.0</div>
            </nav>
            <div id="main">
                <header id="header">
                    <div class="header-left">
                        <button id="menu-toggle">&#9776;</button>
                        <div id="breadcrumb" class="breadcrumb"></div>
                    </div>
                    <div class="header-right">
                        <div class="user-menu" id="user-menu">
                            <div class="user-avatar">${initials}</div>
                            <span style="font-size:13px;">${Utils.esc(this.user.name)}</span>
                            <span style="font-size:10px;">&#9660;</span>
                        </div>
                        <div class="dropdown-menu" id="user-dropdown">
                            <div class="dropdown-item" onclick="App.navigate('settings')">Settings</div>
                            <div class="dropdown-divider"></div>
                            <div class="dropdown-item danger" onclick="App.doLogout()">Sign Out</div>
                        </div>
                    </div>
                </header>
                <div id="content">
                    <div class="loading-overlay"><div class="spinner"></div><span>Loading...</span></div>
                </div>
            </div>
        `;
    },

    bindEvents() {
        // Nav items
        document.querySelectorAll('.nav-item[data-page]').forEach(el => {
            el.addEventListener('click', () => {
                this.navigate(el.dataset.page);
                document.getElementById('sidebar').classList.remove('open');
            });
        });

        // Menu toggle
        document.getElementById('menu-toggle')?.addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });

        // User dropdown
        document.getElementById('user-menu')?.addEventListener('click', (e) => {
            e.stopPropagation();
            document.getElementById('user-dropdown').classList.toggle('show');
        });
        document.addEventListener('click', () => {
            document.querySelectorAll('.dropdown-menu.show').forEach(el => el.classList.remove('show'));
        });
    },

    navigate(page, params = {}) {
        const hash = '#/' + page + (params.id ? '/' + params.id : '') + (params.sub ? '/' + params.sub : '');
        window.location.hash = hash;
    },

    handleRoute() {
        const hash = window.location.hash || '#/dashboard';
        const parts = hash.replace('#/', '').split('/');
        const page = parts[0] || 'dashboard';
        const id = parts[1] || null;
        const sub = parts[2] || null;

        // Update active nav
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });

        // Update breadcrumb
        const breadcrumb = document.getElementById('breadcrumb');
        if (breadcrumb) {
            const pageNames = {
                dashboard: 'Dashboard', contacts: 'Contacts', lists: 'Lists & Segments',
                tags: 'Tags', campaigns: 'Campaigns', templates: 'Templates',
                automations: 'Automations', forms: 'Forms', pages: 'Landing Pages', settings: 'Settings',
            };
            breadcrumb.innerHTML = `<span style="cursor:pointer" onclick="App.navigate('dashboard')">Home</span> <span>/</span> <span>${pageNames[page] || page}</span>`;
        }

        this.currentPage = page;
        this.loadPage(page, id, sub);
    },

    async loadPage(page, id, sub) {
        const content = document.getElementById('content');
        content.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><span>Loading...</span></div>';

        try {
            switch (page) {
                case 'dashboard': await Pages.dashboard(content); break;
                case 'contacts': id ? await Pages.contactDetail(content, id) : await Pages.contacts(content); break;
                case 'lists': id ? await Pages.listDetail(content, id) : await Pages.lists(content); break;
                case 'tags': await Pages.tags(content); break;
                case 'campaigns': id && sub === 'edit' ? await Pages.campaignEdit(content, id) : id ? await Pages.campaignDetail(content, id) : await Pages.campaigns(content); break;
                case 'templates': id ? await Pages.templateEdit(content, id) : await Pages.templates(content); break;
                case 'automations': id ? await Pages.automationEdit(content, id) : await Pages.automations(content); break;
                case 'forms': id ? await Pages.formEdit(content, id) : await Pages.forms(content); break;
                case 'pages': id ? await Pages.pageEdit(content, id) : await Pages.pages(content); break;
                case 'settings': await Pages.settings(content); break;
                default: content.innerHTML = '<div class="empty-state"><h3>Page not found</h3></div>';
            }
        } catch (err) {
            content.innerHTML = `<div class="empty-state"><h3>Error</h3><p>${Utils.esc(err.message)}</p></div>`;
        }
    },

    async doLogout() {
        await API.logout();
        this.showLogin();
    },
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
