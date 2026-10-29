import type { PageQuery } from './api';
import type { UserRole } from './auth';

export const AUDIT_ACTIONS = [
  'LOGIN',
  'LOGIN_FAILED',
  'LOGOUT',
  'DOCUMENT_UPLOADED',
  'SCAN_STARTED',
  'SCAN_COMPLETED',
  'SCAN_FAILED',
  'FINDINGS_VIEWED',
  'PII_REVEALED',
  'DOCUMENT_DOWNLOADED',
  'REPORT_GENERATED',
  'REPORT_DOWNLOADED',
  'REDACTION_CREATED',
  'DOCUMENT_DELETED',
  'SETTINGS_UPDATED',
  'PASSWORD_CHANGED',
  'USER_CREATED',
  'USER_UPDATED',
] as const;

export type AuditAction = (typeof AUDIT_ACTIONS)[number];

export type AuditResult = 'SUCCESS' | 'FAILURE' | 'DENIED';

export interface AuditLog {
  id: string;
  timestamp: string;
  /** "public" marks anonymous uploads from the public scan page; "unknown" marks system actions. */
  user: { id: string | null; name: string; role: UserRole | 'public' | 'unknown' };
  action: AuditAction;
  documentId: string | null;
  documentName: string | null;
  result: AuditResult;
  /** Human-readable context. The backend guarantees this never contains PII values. */
  details: string | null;
}

export interface AuditQuery extends PageQuery {
  search?: string;
  action?: AuditAction;
  result?: AuditResult;
  userId?: string;
  from?: string;
  to?: string;
}
