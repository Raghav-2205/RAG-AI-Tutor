class ConfigManager {
    constructor() {
        const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
        const originBase = isLocal
            ? `${window.location.origin}/api`
            : '/api';
        const storedApiBase = localStorage.getItem('api_base_url');
        const normalizedStoredBase = storedApiBase ? storedApiBase.trim().replace(/\/+$/, '') : '';

        this.apiBase = isLocal
            ? originBase
            : (normalizedStoredBase || originBase);

        localStorage.setItem('api_base_url', this.apiBase);
        window.API_BASE = this.apiBase;
        window.CONFIG = {
            ...(window.CONFIG || {}),
            API_BASE_URL: this.apiBase
        };

        console.log('Connected to API at:', this.apiBase);
    }

    async fetch(endpoint, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : `${this.apiBase}${endpoint}`;

        const token = localStorage.getItem('token');
        const headers = { ...options.headers };
        if (token) headers.Authorization = `Bearer ${token}`;

        try {
            const res = await fetch(url, { ...options, headers });
            if (res.status === 401) {
                alert('Session expired. Please login again.');
                window.location.href = '/views/login.html';
            }
            return res;
        } catch (err) {
            console.error('Fetch Error:', err);
            throw err;
        }
    }
}

window.config = new ConfigManager();
