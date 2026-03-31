class AuthManager {
    constructor() {
        this.token = localStorage.getItem("token");
        this.user = JSON.parse(localStorage.getItem("user") || "null");
    }

    get isAuthenticated() {
        return !!this.token;
    }

    getDisplayName() {
        return this.user?.name || this.user?.email || "Student";
    }

    async login(email, password) {
        try {
            // OAuth2 expects Form Data
            const formData = new URLSearchParams();
            formData.append('username', email);
            formData.append('password', password);

            const response = await fetch(`${window.config.apiBase}/auth/login`, {
                method: "POST",
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData
            });

            if (!response.ok) {
                let errorMessage = "Login failed";
                const rawError = await response.text();

                try {
                    const errorData = JSON.parse(rawError);
                    if (errorData.detail) {
                        if (typeof errorData.detail === 'string') {
                            errorMessage = errorData.detail;
                        } else if (Array.isArray(errorData.detail)) {
                            errorMessage = errorData.detail.map(e => e.msg).join("\n");
                        } else {
                            errorMessage = JSON.stringify(errorData.detail);
                        }
                    }
                } catch {
                    errorMessage = rawError || `Login failed (${response.status})`;
                }

                throw new Error(errorMessage);
            }

            const data = await response.json();

            // Save Session
            this.token = data.access_token;
            this.user = data.user;
            localStorage.setItem("token", this.token);
            localStorage.setItem("user", JSON.stringify(this.user));

            return { success: true };
        } catch (error) {
            console.error("Login Error:", error);
            return { success: false, error: error.message };
        }
    }

    async register(name, email, password, level = "undergraduate", role = "Student") {
        try {
            const response = await window.config.fetch(`${window.config.apiBase}/auth/register`, {
                method: "POST",
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, password, level, role })
            });

            if (!response.ok) {
                const error = await response.json();
                let errorMessage = "Registration failed";
                if (error.detail) {
                    if (typeof error.detail === 'string') {
                        errorMessage = error.detail;
                    } else if (Array.isArray(error.detail)) {
                        // Handle Pydantic validation errors (array of objects)
                        errorMessage = error.detail.map(e => e.msg).join("\n");
                    } else {
                        errorMessage = JSON.stringify(error.detail);
                    }
                }
                throw new Error(errorMessage);
            }

            // Auto-login after registration
            return await this.login(email, password);

        } catch (error) {
            console.error("Registration Error:", error);
            alert("DEBUG Error: " + (error.message || error));
            return { success: false, error: error.message };
        }
    }

    logout() {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        window.location.href = "/views/login.html";
    }
}

window.auth = new AuthManager();
console.log("Auth JS Loaded v6 - Debug Mode");

// Handlers for HTML Forms
async function handleLogin(event) {
    event.preventDefault();
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    const btn = event.target.querySelector('button');

    btn.textContent = "Logging in...";
    btn.disabled = true;

    const result = await window.auth.login(email, password);

    if (result.success) {
        const role = window.auth.user?.role || 'Student';
        if (role === 'Admin' || role === 'Teacher') window.location.href = '/views/lms.html';
        else window.location.href = '/views/dashboard.html';
    } else {
        alert(result.error);
        btn.textContent = "Login";
        btn.disabled = false;
    }
}

async function handleSignup(event) {
    event.preventDefault();
    const name = document.getElementById('signupName').value;
    const email = document.getElementById('signupEmail').value;
    const password = document.getElementById('signupPassword').value;
    const level = document.getElementById('signupLevel').value;
    const role = document.getElementById('signupRole')?.value || 'Student';
    const btn = event.target.querySelector('button');

    btn.textContent = "Creating Account...";
    btn.disabled = true;

    const result = await window.auth.register(name, email, password, level, role);

    if (result.success) {
        const userRole = window.auth.user?.role || role || 'Student';
        if (userRole === 'Admin' || userRole === 'Teacher') window.location.href = '/views/lms.html';
        else window.location.href = '/views/dashboard.html';
    } else {
        alert(result.error);
        btn.textContent = "Sign Up";
        btn.disabled = false;
    }
}
