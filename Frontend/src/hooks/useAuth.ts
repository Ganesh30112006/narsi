import { useContext } from 'react';
import type { AuthContextValue } from '../app/providers/contexts';
import { AuthContext } from '../app/providers/contexts';
import type { Permission } from '../types/auth';

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}

export function usePermission(permission: Permission): boolean {
  return useAuth().can(permission);
}
