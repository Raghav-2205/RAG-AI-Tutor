class ConfigManager {
    constructor() {
        this.isDevelopment = ['localhost', '127.0.0.1'].includes(window.location.hostname);
        
        // POINT THIS TO YOUR RUNNING BACKEND URL
        this.config = {
            development: {
                apiBase: "http://127.0.0.1:8000/api",
            },
            production: {
                apiBase: "/api",
            }
        };
        
        this.current = this.isDevelopment ? this.config.development : this.config.production;
    }

    get apiBase() {
        return this.current.apiBase;
    }

    async fetch(url, options = {}) {
        // Add Authorization header automatically if token exists
        const token = localStorage.getItem('token');
        
        const defaultHeaders = {
            'Content-Type': 'application/json',
        };

        if (token) {
            defaultHeaders['Authorization'] = `Bearer ${token}`;
        }

        const config = {
            ...options,
            headers: {
                ...defaultHeaders,
                ...options.headers
            }
        };

        try {
            const response = await fetch(url, config);
            
            // Handle Token Expiration (401)
            if (response.status === 401) {
                localStorage.removeItem('token');
                localStorage.removeItem('user');
                window.location.href = '/views/login.html';
                return;
            }
            
            return response;
        } catch (error) {
            console.error("API Request Failed:", error);
            throw error;
        }
    }
}

window.config = new ConfigManager();