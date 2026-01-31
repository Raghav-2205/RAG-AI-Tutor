/* ============================================
   OpenLearnHub - Auth (JWT) Client
   - Stores JWT in localStorage
   - Login/Signup fetch to Flask backend
   - Route protection helpers
   ============================================ */

(() => {
  const API_BASE = "/api";
  const TOKEN_KEY = "olh_token";
  const USER_KEY = "olh_user";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    if (!token) return;
    localStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  function setUser(user) {
    if (!user) return;
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function getUser() {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  async function apiFetch(path, { method = "GET", headers = {}, body } = {}) {
    const token = getToken();
    const isFormData = typeof FormData !== "undefined" && body instanceof FormData;

    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: isFormData ? body : body != null ? JSON.stringify(body) : undefined,
    });

    const contentType = res.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await res.json().catch(() => ({})) : await res.text();

    if (!res.ok) {
      const msg = (data && data.message) || (data && data.error) || (typeof data === "string" ? data : "Request failed");
      throw new Error(msg);
    }

    return data;
  }

  async function login({ email, password }) {
    const data = await apiFetch("/auth/login", {
      method: "POST",
      body: { email, password },
    });

    const token = data.token || data.access_token || data.jwt;
    if (token) setToken(token);
    if (data.user) setUser(data.user);

    return data;
  }

  async function signup({ name, email, password, level }) {
    const data = await apiFetch("/auth/signup", {
      method: "POST",
      body: { name, email, password, level },
    });

    const token = data.token || data.access_token || data.jwt;
    if (token) setToken(token);
    if (data.user) setUser(data.user);

    return data;
  }

  function logout({ redirectTo = "index.html" } = {}) {
    clearToken();
    if (redirectTo) window.location.href = redirectTo;
  }

  async function checkAuth({ validateWithServer = false } = {}) {
    const token = getToken();
    if (!token) return false;

    if (!validateWithServer) return true;

    try {
      await apiFetch("/auth/me", { method: "GET" });
      return true;
    } catch {
      clearToken();
      return false;
    }
  }

  async function requireAuth({ redirectTo = "login.html" } = {}) {
    const ok = await checkAuth({ validateWithServer: false });
    if (!ok) window.location.href = redirectTo;
    return ok;
  }

  function bindAuthForms() {
    const loginForm = document.querySelector("[data-auth-form='login']");
    const signupForm = document.querySelector("[data-auth-form='signup']");

    if (loginForm) {
      loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const submitBtn = loginForm.querySelector("button[type='submit']");
        const statusEl = loginForm.querySelector("[data-auth-status]");

        const email = loginForm.querySelector("input[name='email']")?.value?.trim();
        const password = loginForm.querySelector("input[name='password']")?.value;

        try {
          if (submitBtn) submitBtn.disabled = true;
          if (statusEl) statusEl.textContent = "Signing you in...";
          await login({ email, password });
          window.location.href = "subjects.html";
        } catch (err) {
          if (statusEl) statusEl.textContent = err?.message || "Login failed";
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }

    if (signupForm) {
      signupForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const submitBtn = signupForm.querySelector("button[type='submit']");
        const statusEl = signupForm.querySelector("[data-auth-status]");

        const name = signupForm.querySelector("input[name='name']")?.value?.trim();
        const email = signupForm.querySelector("input[name='email']")?.value?.trim();
        const password = signupForm.querySelector("input[name='password']")?.value;
        const level = signupForm.querySelector("select[name='level']")?.value;

        try {
          if (submitBtn) submitBtn.disabled = true;
          if (statusEl) statusEl.textContent = "Creating your account...";
          await signup({ name, email, password, level });
          window.location.href = "subjects.html";
        } catch (err) {
          if (statusEl) statusEl.textContent = err?.message || "Signup failed";
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }
  }

  window.OLH_AUTH = {
    API_BASE,
    getToken,
    setToken,
    clearToken,
    getUser,
    setUser,
    apiFetch,
    login,
    signup,
    logout,
    checkAuth,
    requireAuth,
    bindAuthForms,
  };

  window.checkAuth = checkAuth;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindAuthForms);
  } else {
    bindAuthForms();
  }
})();
