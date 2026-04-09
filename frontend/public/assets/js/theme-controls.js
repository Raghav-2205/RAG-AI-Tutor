(() => {
  const STORAGE_KEY = 'lms_theme';
  const root = document.documentElement;

  function syncThemeButtons(theme) {
    document.querySelectorAll('.theme-toggle-btn').forEach((button) => {
      button.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
      const icon = button.querySelector('i');
      const nextClass = theme === 'dark' ? 'fa-sun' : 'fa-moon';
      const prevClass = theme === 'dark' ? 'fa-moon' : 'fa-sun';

      if (icon) {
        icon.classList.remove(prevClass);
        icon.classList.add(nextClass);
      } else {
        button.innerHTML = `<i class="fa-solid ${nextClass}" aria-hidden="true"></i>`;
      }
    });
  }

  function getSavedTheme() {
    return localStorage.getItem(STORAGE_KEY) || (root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');
  }

  function applyTheme(theme) {
    const nextTheme = theme === 'dark' ? 'dark' : 'light';
    if (nextTheme === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.removeAttribute('data-theme');
    }
    localStorage.setItem(STORAGE_KEY, nextTheme);
    syncThemeButtons(nextTheme);
    document.dispatchEvent(new CustomEvent('lms:themechange', { detail: { theme: nextTheme } }));
    return nextTheme;
  }

  function toggleTheme() {
    return applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  }

  window.getSavedTheme = getSavedTheme;
  window.applyTheme = applyTheme;
  window.toggleTheme = toggleTheme;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => applyTheme(getSavedTheme()), { once: true });
  } else {
    applyTheme(getSavedTheme());
  }
})();
