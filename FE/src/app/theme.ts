export type ThemeMode = "light" | "dark";

const STORAGE_KEY = "plantwise:theme";

export function getStoredTheme(): ThemeMode | null {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" ? stored : null;
}

export function applyTheme(theme: ThemeMode) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(STORAGE_KEY, theme);
}

/** Resolves the theme to use on first paint: an explicit prior toggle wins,
 * otherwise always light. Plantwise's visual identity (white workspace,
 * black chrome, a single yellow accent) is designed as a light-first
 * experience — silently following the OS dark-mode preference would show
 * a very different, all-dark app on first visit for a lot of users, so we
 * deliberately don't do that. Users can still switch to dark via the
 * topbar toggle; that explicit choice is what gets persisted. */
export function resolveInitialTheme(): ThemeMode {
  return getStoredTheme() ?? "light";
}
