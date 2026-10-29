import { createContext } from 'react';
import type { LoginCredentials, Permission, User } from '../../types/auth';
import type { DensityPreference, InterfacePreferences, ThemePreference } from '../../types/settings';

/** "idle": nothing checked yet — public pages never need a session, so restoring waits for an admin route. */
export type AuthStatus = 'idle' | 'restoring' | 'authenticated' | 'anonymous';

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  /** Checks the session cookie once (no-op after the first call). Called by the admin route guards. */
  restore(): void;
  /** True when the user was signed out because their session expired. */
  sessionExpired: boolean;
  login(credentials: LoginCredentials): Promise<User>;
  logout(): Promise<void>;
  /** Clears local state after the backend has already ended the session. */
  endSession(): void;
  updateUser(user: User): void;
  can(permission: Permission): boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export type ToastTone = 'success' | 'warning' | 'error' | 'info';

export interface ToastOptions {
  tone?: ToastTone;
  title: string;
  description?: string;
  /** ms; 0 keeps it until dismissed. */
  duration?: number;
}

export interface ToastContextValue {
  notify(options: ToastOptions): string;
  dismiss(id: string): void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export interface PreferencesContextValue extends InterfacePreferences {
  resolvedTheme: 'light' | 'dark';
  setTheme(theme: ThemePreference): void;
  setDensity(density: DensityPreference): void;
}

export const PreferencesContext = createContext<PreferencesContextValue | null>(null);
