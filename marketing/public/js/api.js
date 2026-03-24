/**
 * MarketFlow API Client
 */
const API = {
    baseUrl: '/api',

    async request(method, path, body = null, isFormData = false) {
        const opts = {
            method,
            headers: {},
            credentials: 'same-origin',
        };
        if (body && !isFormData) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        } else if (body && isFormData) {
            opts.body = body;
        }
        const res = await fetch(this.baseUrl + path, opts);
        if (res.status === 401 && !path.includes('/auth/')) {
            App.showLogin();
            throw new Error('Unauthorized');
        }
        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('text/csv')) {
            return { blob: await res.blob(), ok: res.ok };
        }
        const data = contentType.includes('application/json') ? await res.json() : await res.text();
        if (!res.ok) throw new Error(data.error || data || 'Request failed');
        return data;
    },

    get(path) { return this.request('GET', path); },
    post(path, body) { return this.request('POST', path, body); },
    put(path, body) { return this.request('PUT', path, body); },
    del(path) { return this.request('DELETE', path); },
    upload(path, formData) { return this.request('POST', path, formData, true); },

    // Auth
    login(email, password) { return this.post('/auth/login', { email, password }); },
    logout() { return this.post('/auth/logout'); },
    me() { return this.get('/auth/me'); },

    // Dashboard
    dashboardStats() { return this.get('/dashboard/stats'); },
    dashboardCharts(period = 30) { return this.get(`/dashboard/charts?period=${period}`); },
    dashboardActivity(limit = 20) { return this.get(`/dashboard/activity?limit=${limit}`); },

    // Contacts
    contacts(params = '') { return this.get(`/contacts${params ? '?' + params : ''}`); },
    contact(id) { return this.get(`/contacts/${id}`); },
    createContact(data) { return this.post('/contacts', data); },
    updateContact(id, data) { return this.put(`/contacts/${id}`, data); },
    deleteContact(id) { return this.del(`/contacts/${id}`); },
    bulkContacts(data) { return this.post('/contacts/bulk', data); },
    importContacts(formData) { return this.upload('/contacts/import', formData); },

    // Lists
    lists(params = '') { return this.get(`/lists${params ? '?' + params : ''}`); },
    list(id) { return this.get(`/lists/${id}`); },
    createList(data) { return this.post('/lists', data); },
    updateList(id, data) { return this.put(`/lists/${id}`, data); },
    deleteList(id) { return this.del(`/lists/${id}`); },

    // Campaigns
    campaigns(params = '') { return this.get(`/campaigns${params ? '?' + params : ''}`); },
    campaign(id) { return this.get(`/campaigns/${id}`); },
    createCampaign(data) { return this.post('/campaigns', data); },
    updateCampaign(id, data) { return this.put(`/campaigns/${id}`, data); },
    deleteCampaign(id) { return this.del(`/campaigns/${id}`); },
    sendCampaign(id) { return this.post(`/campaigns/${id}/send`); },
    scheduleCampaign(id, data) { return this.post(`/campaigns/${id}/schedule`, data); },
    duplicateCampaign(id) { return this.post(`/campaigns/${id}/duplicate`); },
    previewCampaign(id) { return this.get(`/campaigns/${id}/preview`); },
    testCampaign(id, email) { return this.post(`/campaigns/${id}/test`, { email }); },

    // Templates
    templates(params = '') { return this.get(`/templates${params ? '?' + params : ''}`); },
    template(id) { return this.get(`/templates/${id}`); },
    createTemplate(data) { return this.post('/templates', data); },
    updateTemplate(id, data) { return this.put(`/templates/${id}`, data); },
    deleteTemplate(id) { return this.del(`/templates/${id}`); },
    duplicateTemplate(id) { return this.post(`/templates/${id}/duplicate`); },
    templateStarters() { return this.get('/templates/starters'); },

    // Automations
    automations(params = '') { return this.get(`/automations${params ? '?' + params : ''}`); },
    automation(id) { return this.get(`/automations/${id}`); },
    createAutomation(data) { return this.post('/automations', data); },
    updateAutomation(id, data) { return this.put(`/automations/${id}`, data); },
    deleteAutomation(id) { return this.del(`/automations/${id}`); },
    activateAutomation(id) { return this.post(`/automations/${id}/activate`); },
    pauseAutomation(id) { return this.post(`/automations/${id}/pause`); },
    triggerTypes() { return this.get('/automations/trigger-types'); },

    // Forms
    forms(params = '') { return this.get(`/forms${params ? '?' + params : ''}`); },
    form(id) { return this.get(`/forms/${id}`); },
    createForm(data) { return this.post('/forms', data); },
    updateForm(id, data) { return this.put(`/forms/${id}`, data); },
    deleteForm(id) { return this.del(`/forms/${id}`); },
    formSubmissions(id, params = '') { return this.get(`/forms/${id}/submissions${params ? '?' + params : ''}`); },

    // Landing Pages
    pages(params = '') { return this.get(`/pages${params ? '?' + params : ''}`); },
    page(id) { return this.get(`/pages/${id}`); },
    createPage(data) { return this.post('/pages', data); },
    updatePage(id, data) { return this.put(`/pages/${id}`, data); },
    deletePage(id) { return this.del(`/pages/${id}`); },
    duplicatePage(id) { return this.post(`/pages/${id}/duplicate`); },

    // Settings
    settings() { return this.get('/settings'); },
    updateSettings(data) { return this.post('/settings', data); },
    testSmtp(data) { return this.post('/settings/test-smtp', data); },
    testEmail(email) { return this.post('/settings/test-email', { email }); },

    // Tags
    tags() { return this.get('/tags'); },
    createTag(data) { return this.post('/tags', data); },
    updateTag(id, data) { return this.put(`/tags/${id}`, data); },
    deleteTag(id) { return this.del(`/tags/${id}`); },

    // Custom Fields
    customFields() { return this.get('/custom-fields'); },
    createCustomField(data) { return this.post('/custom-fields', data); },
    deleteCustomField(id) { return this.del(`/custom-fields/${id}`); },

    // Users
    users() { return this.get('/users'); },
    createUser(data) { return this.post('/users', data); },
    updateProfile(data) { return this.put('/profile', data); },
};
