class ConfigManager {
    constructor() {
        // Automatically detect if we are on localhost
        const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);

        this.apiBase = isLocal
            ? "http://127.0.0.1:8002/api"  // Python Backend URL
            : "/api";                      // Production URL

        console.log("🔌 Connected to API at:", this.apiBase);
    }

    async fetch(endpoint, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : `${this.apiBase}${endpoint}`;

        // Auto-attach Token
        const token = localStorage.getItem('token');
        const headers = { ...options.headers };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        try {
            const res = await fetch(url, { ...options, headers });
            if (res.status === 401) {
                alert("Session expired. Please login again.");
                window.location.href = "/views/login.html";
            }
            return res;
        } catch (err) {
            console.error("Fetch Error:", err);
            throw err;
        }
    }
}
window.config = new ConfigManager();