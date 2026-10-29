import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../../services/api';
import { ApiError } from '../../services/apiError';
import { authApi } from '../../services/authApi';
import type { LoginCredentials, Permission, User } from '../../types/auth';
import { hasPermission } from '../../utils/security';
import type { AuthContextValue, AuthStatus } from './contexts';
import { AuthContext } from './contexts';

/**
 * Session state lives in memory only. The backend owns the session via an HTTP-only cookie;
 * no tokens are ever stored in localStorage or exposed to scripts.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('idle');
  const [user, setUser] = useState<User | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const userRef = useRef<User | null>(null);

  useEffect(() => {
    userRef.current = user;
  }, [user]);

  // Restore the session from the cookie the first time an admin route asks for it.
  const restoreStarted = useRef(false);
  const restore = useCallback(() => {
    if (restoreStarted.current) return;
    restoreStarted.current = true;
    setStatus((current) => (current === 'idle' ? 'restoring' : current));
    authApi
      .getCurrentUser()
      .then((current) => {
        setUser(current);
        setStatus('authenticated');
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.kind === 'cancelled') return;
        setUser(null);
        setStatus((current) => (current === 'authenticated' ? current : 'anonymous'));
      });
  }, []);

  // Any 401 from a protected request means the session has expired.
  useEffect(
    () =>
      api.onUnauthorized(() => {
        if (userRef.current) setSessionExpired(true);
        setUser(null);
        setStatus('anonymous');
      }),
    [],
  );

  const login = useCallback(async (credentials: LoginCredentials) => {
    const signedIn = await authApi.login(credentials);
    restoreStarted.current = true;
    setUser(signedIn);
    setSessionExpired(false);
    setStatus('authenticated');
    return signedIn;
  }, []);

  const endSession = useCallback(() => {
    setUser(null);
    setSessionExpired(false);
    setStatus('anonymous');
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      // Even if the request fails, clear local state so the UI never shows a stale session.
      endSession();
    }
  }, [endSession]);

  const can = useCallback((permission: Permission) => hasPermission(user?.role, permission), [user]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, restore, sessionExpired, login, logout, endSession, updateUser: setUser, can }),
    [status, user, restore, sessionExpired, login, logout, endSession, can],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
