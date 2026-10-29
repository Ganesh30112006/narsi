import { useContext } from 'react';
import type { ToastContextValue } from '../app/providers/contexts';
import { ToastContext } from '../app/providers/contexts';

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within ToastProvider');
  return context;
}
