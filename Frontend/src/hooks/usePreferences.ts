import { useContext } from 'react';
import type { PreferencesContextValue } from '../app/providers/contexts';
import { PreferencesContext } from '../app/providers/contexts';

export function usePreferences(): PreferencesContextValue {
  const context = useContext(PreferencesContext);
  if (!context) throw new Error('usePreferences must be used within PreferencesProvider');
  return context;
}
