import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { DensityPreference, InterfacePreferences, ThemePreference } from '../../types/settings';
import type { PreferencesContextValue } from './contexts';
import { PreferencesContext } from './contexts';

const STORAGE_KEY = 'govpii.interface';
const DEFAULTS: InterfacePreferences = { theme: 'system', density: 'comfortable' };

/** Interface preferences are non-sensitive, so localStorage is appropriate here. */
function readStored(): InterfacePreferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<InterfacePreferences>;
    return {
      theme: parsed.theme === 'light' || parsed.theme === 'dark' ? parsed.theme : 'system',
      density: parsed.density === 'compact' ? 'compact' : 'comfortable',
    };
  } catch {
    return DEFAULTS;
  }
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<InterfacePreferences>(readStored);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const resolvedTheme = preferences.theme === 'system' ? (systemDark ? 'dark' : 'light') : preferences.theme;

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;
    root.dataset.density = preferences.density;
  }, [resolvedTheme, preferences.density]);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
    } catch {
      // Storage unavailable — preferences apply for this session only.
    }
  }, [preferences]);

  const setTheme = useCallback((theme: ThemePreference) => setPreferences((current) => ({ ...current, theme })), []);
  const setDensity = useCallback((density: DensityPreference) => setPreferences((current) => ({ ...current, density })), []);

  const value = useMemo<PreferencesContextValue>(
    () => ({ ...preferences, resolvedTheme, setTheme, setDensity }),
    [preferences, resolvedTheme, setTheme, setDensity],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}
