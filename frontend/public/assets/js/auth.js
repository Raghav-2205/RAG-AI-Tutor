const routeGuard = window.routeGuard || {
    normalizeRole(role) {
        return String(role || "student").trim().toLowerCase() || "student";
    },
    readStoredUser() {
        try {
            const raw = localStorage.getItem("user");
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            return parsed ? { ...parsed, role: this.normalizeRole(parsed.role) } : null;
        } catch {
            return null;
        }
    },
    storeUser(user) {
        if (!user) return null;
        const normalized = { ...user, role: this.normalizeRole(user.role) };
        localStorage.setItem("user", JSON.stringify(normalized));
        return normalized;
    },
    clearSession() {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
    },
    homeForRole(role) {
        const normalized = this.normalizeRole(role);
        if (normalized === "teacher" || normalized === "admin") return "/views/lms.html";
        return "/views/dashboard.html";
    },
    redirectToHome(role) {
        window.location.href = this.homeForRole(role);
    },
    redirectToLogin() {
        window.location.href = "/views/login.html";
    },
};

class AuthManager {
    constructor() {
        this.token = localStorage.getItem("token");
        this.user = routeGuard.readStoredUser();
    }

    get isAuthenticated() {
        return !!this.token;
    }

    getDisplayName() {
        return this.user?.name || this.user?.email || "Student";
    }

    async login(email, password) {
        try {
            const formData = new URLSearchParams();
            formData.append("username", email);
            formData.append("password", password);

            const response = await fetch(`${window.config.apiBase}/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: formData,
            });

            if (!response.ok) {
                let errorMessage = "Login failed";
                const rawError = await response.text();

                try {
                    const errorData = JSON.parse(rawError);
                    if (errorData.detail) {
                        if (typeof errorData.detail === "string") {
                            errorMessage = errorData.detail;
                        } else if (Array.isArray(errorData.detail)) {
                            errorMessage = errorData.detail.map((e) => e.msg).join("\n");
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
            this.token = data.access_token;
            this.user = routeGuard.storeUser(data.user);
            localStorage.setItem("token", this.token);

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
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, email, password, level }),
            });

            if (!response.ok) {
                const error = await response.json();
                let errorMessage = "Registration failed";
                if (error.detail) {
                    if (typeof error.detail === "string") {
                        errorMessage = error.detail;
                    } else if (Array.isArray(error.detail)) {
                        errorMessage = error.detail.map((e) => e.msg).join("\n");
                    } else {
                        errorMessage = JSON.stringify(error.detail);
                    }
                }
                throw new Error(errorMessage);
            }

            return await this.login(email, password);
        } catch (error) {
            console.error("Registration Error:", error);
            alert("DEBUG Error: " + (error.message || error));
            return { success: false, error: error.message };
        }
    }

    logout() {
        routeGuard.clearSession();
        routeGuard.redirectToLogin();
    }
}

window.auth = new AuthManager();
console.log("Auth JS Loaded v7 - Role Guarded");

async function handleLogin(event) {
    event.preventDefault();
    const email = document.getElementById("loginEmail").value;
    const password = document.getElementById("loginPassword").value;
    const btn = event.target.querySelector("button");

    btn.textContent = "Logging in...";
    btn.disabled = true;

    const result = await window.auth.login(email, password);

    if (result.success) {
        routeGuard.redirectToHome(window.auth.user?.role);
        return;
    }

    alert(result.error);
    btn.textContent = "Login";
    btn.disabled = false;
}

async function handleSignup(event) {
    event.preventDefault();
    const name = document.getElementById("signupName").value;
    const email = document.getElementById("signupEmail").value;
    const password = document.getElementById("signupPassword").value;
    const level = document.getElementById("signupLevel")?.value || "undergraduate";
    const btn = event.target.querySelector("button");

    btn.textContent = "Creating Account...";
    btn.disabled = true;

    const result = await window.auth.register(name, email, password, level);

    if (result.success) {
        routeGuard.redirectToHome(window.auth.user?.role);
        return;
    }

    alert(result.error);
    btn.textContent = "Sign Up";
    btn.disabled = false;
}
