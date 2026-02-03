/**
 * Enhanced Authentication Manager
 * Handles user authentication with proper error handling and token management
 */
class AuthManager {
  constructor() {
    this.token = localStorage.getItem("token");
    this.user = JSON.parse(localStorage.getItem("user") || "null");
    this.refreshTimer = null;
    
    // Auto-refresh token before expiration
    if (this.token) {
      this.scheduleTokenRefresh();
    }
  }

  get apiBase() {
    return window.config ? window.config.apiBase : "http://127.0.0.1:8000/api";
  }

  get isAuthenticated() {
    return !!this.token && !!this.user;
  }

  async login(email, password) {
    try {
      const response = await this.makeRequest(`${this.apiBase}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          username: email,
          password: password
        })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Invalid credentials");
      }

      const data = await response.json();
      
      // Store token and schedule refresh
      this.token = data.access_token;
      localStorage.setItem("token", this.token);
      this.scheduleTokenRefresh();

      // Fetch user info
      await this.fetchUser();
      
      return { success: true, user: this.user };
    } catch (error) {
      console.error('Login error:', error);
      return { success: false, error: error.message };
    }
  }

  async register(email, password, name, level) {
    try {
      const response = await this.makeRequest(`${this.apiBase}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          email: email.toLowerCase(), 
          password, 
          name, 
          level: level.toLowerCase() 
        })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Registration failed");
      }

      // Auto-login after successful registration
      return await this.login(email, password);
    } catch (error) {
      console.error('Registration error:', error);
      return { success: false, error: error.message };
    }
  }

  async fetchUser() {
    try {
      const response = await this.makeRequest(`${this.apiBase}/auth/me`, {
        headers: { Authorization: `Bearer ${this.token}` }
      });

      if (!response.ok) {
        throw new Error('Failed to fetch user info');
      }

      this.user = await response.json();
      localStorage.setItem("user", JSON.stringify(this.user));
      return this.user;
    } catch (error) {
      console.error('Fetch user error:', error);
      this.logout();
      throw error;
    }
  }

  async refreshToken() {
    try {
      const response = await this.makeRequest(`${this.apiBase}/auth/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${this.token}` }
      });

      if (response.ok) {
        const data = await response.json();
        this.token = data.access_token;
        localStorage.setItem("token", this.token);
        this.scheduleTokenRefresh();
        return true;
      }
    } catch (error) {
      console.error('Token refresh failed:', error);
    }
    
    // If refresh fails, logout
    this.logout();
    return false;
  }

  scheduleTokenRefresh() {
    // Clear existing timer
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
    }
    
    // Schedule refresh 5 minutes before expiration (25 minutes for 30-minute tokens)
    const refreshTime = 25 * 60 * 1000; // 25 minutes in milliseconds
    this.refreshTimer = setTimeout(() => {
      this.refreshToken();
    }, refreshTime);
  }

  logout() {
    // Clear timers
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    
    // Clear storage
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    this.token = null;
    this.user = null;
    
    // Redirect to login
    window.location.href = "/views/login.html";
  }

  async makeRequest(url, options = {}) {
    if (window.config && window.config.fetch) {
      return await window.config.fetch(url, options);
    } else {
      // Fallback to regular fetch
      return await fetch(url, options);
    }
  }

  // Utility method to check if user has specific permissions
  hasPermission(permission) {
    return this.user && this.user.permissions && this.user.permissions.includes(permission);
  }

  // Get user's display name
  getDisplayName() {
    return this.user ? (this.user.name || this.user.email) : 'Guest';
  }
}

// Global auth instance
window.auth = new AuthManager();

/* Enhanced SPA handlers with better error handling */
window.handleLogin = async (e) => {
  e.preventDefault();
  
  const submitBtn = e.target.querySelector('button[type="submit"]');
  const originalText = submitBtn.textContent;
  
  try {
    // Show loading state
    submitBtn.textContent = 'Signing in...';
    submitBtn.disabled = true;
    
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    
    if (!email || !password) {
      throw new Error('Please fill in all fields');
    }
    
    const result = await auth.login(email, password);
    
    if (result.success) {
      // Show success message briefly
      submitBtn.textContent = 'Success!';
      setTimeout(() => {
        // Redirect to subjects page
        window.location.href = "/views/subjects.html";
      }, 500);
    } else {
      throw new Error(result.error);
    }
  } catch (error) {
    // Show error
    alert(error.message);
    console.error('Login error:', error);
  } finally {
    // Reset button state
    setTimeout(() => {
      submitBtn.textContent = originalText;
      submitBtn.disabled = false;
    }, 1000);
  }
};

window.handleSignup = async (e) => {
  e.preventDefault();
  
  const submitBtn = e.target.querySelector('button[type="submit"]');
  const originalText = submitBtn.textContent;
  
  try {
    // Show loading state
    submitBtn.textContent = 'Creating account...';
    submitBtn.disabled = true;
    
    const email = document.getElementById('signupEmail').value;
    const password = document.getElementById('signupPassword').value;
    const name = document.getElementById('signupName').value;
    const level = document.getElementById('signupLevel').value;
    
    if (!email || !password || !name || !level) {
      throw new Error('Please fill in all fields');
    }
    
    if (password.length < 8) {
      throw new Error('Password must be at least 8 characters long');
    }
    
    const result = await auth.register(email, password, name, level);
    
    if (result.success) {
      // Show success message briefly
      submitBtn.textContent = 'Account created!';
      setTimeout(() => {
        // Redirect to subjects page
        window.location.href = "/views/subjects.html";
      }, 500);
    } else {
      throw new Error(result.error);
    }
  } catch (error) {
    // Show error
    alert(error.message);
    console.error('Signup error:', error);
  } finally {
    // Reset button state
    setTimeout(() => {
      submitBtn.textContent = originalText;
      submitBtn.disabled = false;
    }, 1000);
  }
};

// Auto-check authentication on page load
document.addEventListener('DOMContentLoaded', () => {
  // Check if we're on a protected page
  const protectedPages = ['/views/subjects.html', '/views/chat.html', '/views/upload.html'];
  const currentPath = window.location.pathname;
  
  if (protectedPages.some(page => currentPath.includes(page))) {
    if (!auth.isAuthenticated) {
      window.location.href = '/views/login.html';
    }
  }
});
