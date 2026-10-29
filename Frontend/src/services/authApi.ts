import type { ChangePasswordRequest, LoginCredentials, SessionInfo, User } from '../types/auth';
import { api } from './api';

export interface AuthService {
  login(credentials: LoginCredentials): Promise<User>;
  logout(): Promise<void>;
  /** Restores the session from the HTTP-only cookie. Rejects with `unauthorized` when there is none. */
  getCurrentUser(signal?: AbortSignal): Promise<User>;
  changePassword(request: ChangePasswordRequest): Promise<void>;
  updateProfile(changes: { name: string }): Promise<User>;
  listSessions(signal?: AbortSignal): Promise<SessionInfo[]>;
  /** Signs out every session, including this one. */
  revokeAllSessions(): Promise<void>;
}

export const authApi: AuthService = {
  login: (credentials) => api.post<User>('/auth/login', credentials, { skipAuthHandling: true }),
  logout: () => api.post<void>('/auth/logout', undefined, { skipAuthHandling: true }),
  getCurrentUser: (signal) => api.get<User>('/auth/me', { signal, skipAuthHandling: true }),
  changePassword: (request) => api.post<void>('/auth/change-password', request),
  updateProfile: (changes) => api.patch<User>('/users/me', changes),
  listSessions: (signal) => api.get<SessionInfo[]>('/auth/sessions', { signal }),
  revokeAllSessions: () => api.post<void>('/auth/sessions/revoke-all'),
};
