/** Administrators are the only accounts that sign in; everyone else uses the public upload page. */
export type UserRole = 'admin';

export interface User {
  id: string;
  name: string;
  username: string;
  role: UserRole;
  createdAt: string;
  lastLoginAt: string | null;
  permissions?: Permission[];
  isActive?: boolean;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface ChangePasswordRequest {
  currentPassword: string;
  newPassword: string;
}

export interface SessionInfo {
  id: string;
  device: string;
  location: string | null;
  createdAt: string;
  lastActiveAt: string;
  current: boolean;
}

export type Permission =
  | 'documents:read'
  | 'documents:upload'
  | 'documents:download'
  | 'documents:delete'
  | 'scans:create'
  | 'findings:read'
  | 'pii:reveal'
  | 'redactions:create'
  | 'reports:read'
  | 'reports:export'
  | 'audit:read'
  | 'settings:manage';
