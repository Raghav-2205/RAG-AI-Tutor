class AuthManager {
    constructor() {
        this.token = localStorage.getItem("token");
        this.user = JSON.parse(localStorage.getItem("user") || "null");
    }

    get isAuthenticated() {
        return !!this.token;
    }

    async login(email, password) {
        try {
            // IMPORTANT: Backend expects Form Data for OAuth2 login, not JSON!
            const formData = new URLSearchParams();
            formData.append('username', email); // OAuth2 expects 'username', even if it is email
            formData.append('password', password);

            const response = await fetch(`${window.config.apiBase}/auth/login`, {
                method: "POST",
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || "Login failed");
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

    async register(name, email, password, level = "undergraduate") {
        try {
            const response = await window.config.fetch(`${window.config.apiBase}/auth/register`, {
                method: "POST",
                body: JSON.stringify({ name, email, password, level })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || "Registration failed");
            }
            
            // Auto-login after registration
            return await this.login(email, password);

        } catch (error) {
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

// Handle Login Form Submit
async function handleLogin(event) {
    event.preventDefault();
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    const btn = event.target.querySelector('button');

    btn.textContent = "Logging in...";
    btn.disabled = true;

    const result = await window.auth.login(email, password);

    if (result.success) {
        window.location.href = "/views/subjects.html"; // Redirect to dashboard
    } else {
        alert(result.error);
        btn.textContent = "Login";
        btn.disabled = false;
    }
}

// Handle Signup Form Submit
async function handleSignup(event) {
    event.preventDefault();
    const name = document.getElementById('signupName').value;
    const email = document.getElementById('signupEmail').value;
    const password = document.getElementById('signupPassword').value;
    const level = document.getElementById('signupLevel').value;
    const btn = event.target.querySelector('button');

    btn.textContent = "Creating Account...";
    btn.disabled = true;

    const result = await window.auth.register(name, email, password, level);

    if (result.success) {
        window.location.href = "/views/subjects.html";
    } else {
        alert(result.error);
        btn.textContent = "Sign Up";
        btn.disabled = false;
    }
}