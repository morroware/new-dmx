/**
 * NEXUS API Client
 */
const API = {
    base: '/api',
    async req(method, path, body = null) {
        const opts = { method, headers: {}, credentials: 'same-origin' };
        if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
        const res = await fetch(this.base + path, opts);
        if (res.status === 401 && !path.includes('/auth/')) { App.showLogin(); throw new Error('Unauthorized'); }
        const ct = res.headers.get('content-type') || '';
        if (ct.includes('text/csv')) return { blob: await res.blob(), ok: res.ok };
        const data = ct.includes('json') ? await res.json() : await res.text();
        if (!res.ok) throw new Error(data.error || data || 'Request failed');
        return data;
    },
    get: (p) => API.req('GET', p),
    post: (p, b) => API.req('POST', p, b),
    put: (p, b) => API.req('PUT', p, b),
    del: (p) => API.req('DELETE', p),
    upload(path, formData) {
        return fetch(this.base + path, { method: 'POST', body: formData, credentials: 'same-origin' }).then(r => r.json());
    },
};
