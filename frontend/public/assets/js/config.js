/**
 * Frontend Configuration Manager
 * Handles environment-specific settings and API endpoints
 */
class ConfigManager {
  constructor() {
    // Detect environment
    this.isDevelopment = window.location.hostname === 'localhost' || 
                        window.location.hostname === '127.0.0.1';
    
    // API Configuration
    this.config = {
      development: {
        apiBase: "http://127.0.0.1:8000/api",
        wsBase: "ws://127.0.0.1:8000/ws"
      },
      production: {
        apiBase: "/api",  // Relative URL for production
        wsBase: `ws://${window.location.host}/ws`
      }
    };
    
    // Get current environment config
    this.current = this.isDevelopment ? this.config.development : this.config.production;
    
    // Request configuration
    this.requestDefaults = {
      timeout: 30000, // 30 seconds
      retries: 3,
      retryDelay: 1000 // 1 second
    };
    
    console.log(`🔧 Config loaded for ${this.isDevelopment ? 'development' : 'production'}`);
    console.log(`📡 API Base: ${this.current.apiBase}`);
  }
  
  get apiBase() {
    return this.current.apiBase;
  }
  
  get wsBase() {
    return this.current.wsBase;
  }
  
  /**
   * Create fetch request with default configuration
   */
  async fetch(url, options = {}) {
    const defaultOptions = {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      ...options
    };
    
    // Add auth token if available
    const token = localStorage.getItem('token');
    if (token) {
      defaultOptions.headers.Authorization = `Bearer ${token}`;
    }
    
    let lastError;
    
    // Retry logic
    for (let attempt = 1; attempt <= this.requestDefaults.retries; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.requestDefaults.timeout);
        
        const response = await fetch(url, {
          ...defaultOptions,
          signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        // Handle token expiration
        if (response.status === 401) {
          this.handleTokenExpiration();
          throw new Error('Authentication required');
        }
        
        return response;
        
      } catch (error) {
        lastError = error;
        
        if (attempt < this.requestDefaults.retries) {
          console.warn(`Request failed (attempt ${attempt}), retrying...`, error.message);
          await this.delay(this.requestDefaults.retryDelay * attempt);
        }
      }
    }
    
    throw lastError;
  }
  
  /**
   * Handle token expiration
   */
  handleTokenExpiration() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    
    // Redirect to login if not already there
    if (!window.location.pathname.includes('login')) {
      window.location.href = '/views/login.html';
    }
  }
  
  /**
   * Delay utility for retries
   */
  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
  
  /**
   * Check if API is available
   */
  async checkHealth() {
    try {
      console.log(`Checking health at: ${this.apiBase}/health`);
      const response = await this.fetch(`${this.apiBase}/health`);
      const isHealthy = response.ok;
      console.log(`Health check result: ${isHealthy}`);
      return isHealthy;
    } catch (error) {
      console.error('Health check failed:', error);
      return false;
    }
  }
}

// Global config instance
window.config = new ConfigManager();

// Export for modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ConfigManager;
}