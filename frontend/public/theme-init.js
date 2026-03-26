// Prevent flash of wrong theme: apply .dark class before first paint.
// Logic must match frontend/src/context/ThemeContext.tsx (STORAGE_KEY + dark resolution).
/* global localStorage, window, document */
(function () {
  try {
    var t = localStorage.getItem('claims_theme');
    if (t !== 'dark' && t !== 'light' && t !== 'system') {
      t = 'system';
    }
    if (t === 'dark' || (t === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    }
  } catch {
    // localStorage may be unavailable (e.g. private-browsing restrictions)
  }
})();
