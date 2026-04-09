(function () {
  function normalizeRole(role) {
    return String(role || 'student').trim().toLowerCase() || 'student';
  }

  function displayRole(role) {
    const normalized = normalizeRole(role);
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  }

  function readStoredUser() {
    try {
      const raw = localStorage.getItem('user');
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      const normalized = { ...parsed, role: normalizeRole(parsed.role) };
      if (JSON.stringify(parsed) !== JSON.stringify(normalized)) {
        localStorage.setItem('user', JSON.stringify(normalized));
      }
      return normalized;
    } catch {
      return null;
    }
  }

  function getSession() {
    const token = localStorage.getItem('token');
    const user = readStoredUser();
    return {
      token,
      user,
      role: normalizeRole(user?.role),
      isAuthenticated: !!token,
    };
  }

  function clearSession() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
  }

  function homeForRole(role) {
    const normalized = normalizeRole(role);
    if (normalized === 'teacher' || normalized === 'admin') return '/views/lms.html';
    return '/views/dashboard.html';
  }

  function redirectToLogin() {
    window.location.href = '/views/login.html';
  }

  function redirectToHome(role) {
    window.location.href = homeForRole(role);
  }

  function requireAuth(options = {}) {
    const session = getSession();
    if (!session.token) {
      redirectToLogin();
      return null;
    }

    if (options.roles && options.roles.length) {
      const allowed = options.roles.map(normalizeRole);
      if (!allowed.includes(session.role)) {
        window.location.href = options.redirectTo || homeForRole(session.role);
        return null;
      }
    }

    return session;
  }

  function storeUser(user) {
    if (!user) return null;
    const normalized = { ...user, role: normalizeRole(user.role) };
    localStorage.setItem('user', JSON.stringify(normalized));
    return normalized;
  }

  window.routeGuard = {
    normalizeRole,
    displayRole,
    readStoredUser,
    getSession,
    clearSession,
    homeForRole,
    redirectToLogin,
    redirectToHome,
    requireAuth,
    storeUser,
  };
})();
