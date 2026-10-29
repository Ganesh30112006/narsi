import type { Permission, UserRole } from '../types/auth';
import type { PIIType } from '../types/finding';

const OPERATOR_PERMISSIONS: Permission[] = [
  'documents:read',
  'documents:upload',
  'documents:download',
  'scans:create',
  'findings:read',
  'redactions:create',
  'reports:read',
  'reports:export',
];

/**
 * Mirrors the backend's role model so the UI can hide actions a user cannot take.
 * This is a convenience only — the backend remains the authority on every request.
 */
export const ROLE_PERMISSIONS: Record<UserRole, ReadonlySet<Permission>> = {
  admin: new Set<Permission>([...OPERATOR_PERMISSIONS, 'documents:delete', 'pii:reveal', 'audit:read', 'settings:manage']),
};

export function hasPermission(role: UserRole | null | undefined, permission: Permission): boolean {
  return role ? ROLE_PERMISSIONS[role].has(permission) : false;
}

export const PERMISSION_LABELS: Record<Permission, string> = {
  'documents:read': 'View documents',
  'documents:upload': 'Upload documents',
  'documents:download': 'Download documents',
  'documents:delete': 'Delete documents',
  'scans:create': 'Start scans',
  'findings:read': 'View findings',
  'pii:reveal': 'Reveal masked values (audited)',
  'redactions:create': 'Create sanitized copies',
  'reports:read': 'View reports',
  'reports:export': 'Export reports',
  'audit:read': 'View audit logs',
  'settings:manage': 'Manage scan and retention settings',
};

/** Characters kept visible at the end of a masked value, by type. */
const VISIBLE_SUFFIX: Record<PIIType, number> = {
  AADHAAR: 4,
  AADHAAR_VID: 4,
  PAN: 4,
  PASSPORT: 3,
  DRIVING_LICENSE: 4,
  VOTER_ID: 3,
  PHONE: 2,
  EMAIL: 0,
  NAME: 0,
  ADDRESS: 0,
  DATE_OF_BIRTH: 0,
  AADHAAR_ENROLMENT: 4,
  ROLL_NUMBER: 3,
  PLACE_OF_BIRTH: 0,
  IDENTIFICATION_MARK: 0,
  PHOTO: 0,
  QR_CODE: 0,
  SIGNATURE: 0,
};

const VISUAL_MASKS: Partial<Record<PIIType, string>> = {
  PHOTO: '[photo]',
  QR_CODE: '[QR code]',
  SIGNATURE: '[signature]',
};

/**
 * Client-side masking. The backend already masks values; this is used as a second line of
 * defence whenever a value must be re-masked (e.g. after a reveal expires).
 */
export function maskValue(value: string, type: PIIType): string {
  const visual = VISUAL_MASKS[type];
  if (visual) return visual;
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (type === 'EMAIL') {
    const [local = '', domain = ''] = trimmed.split('@');
    return `${local.slice(0, 1)}${'•'.repeat(Math.max(local.length - 1, 3))}@${domain}`;
  }
  if (type === 'DATE_OF_BIRTH') return 'XX/XX/XXXX';
  if (type === 'NAME' || type === 'ADDRESS') {
    return trimmed
      .split(/\s+/)
      .map((word) => `${word.slice(0, 1)}${'•'.repeat(Math.max(word.length - 1, 2))}`)
      .join(' ');
  }
  const compact = trimmed.replace(/[\s-]/g, '');
  const visible = VISIBLE_SUFFIX[type];
  const hidden = Math.max(compact.length - visible, 0);
  return `${'X'.repeat(hidden)}${compact.slice(hidden)}`;
}

/**
 * Only allow in-app relative redirects (prevents open-redirects via `?next=`).
 */
export function safeRedirectPath(candidate: string | null | undefined, fallback = '/app/dashboard'): string {
  if (!candidate) return fallback;
  if (!candidate.startsWith('/') || candidate.startsWith('//') || candidate.includes('\\')) return fallback;
  if (!candidate.startsWith('/app')) return fallback;
  return candidate;
}

/** Strips path separators and control characters from a server-provided filename. */
export function sanitizeFileName(name: string, fallback = 'download'): string {
  const cleaned = name
    // eslint-disable-next-line no-control-regex -- control characters are exactly what we strip
    .replace(/[\u0000-\u001f\u007f<>:"/\\|?*]+/g, '_')
    .replace(/^\.+/, '')
    .trim();
  return cleaned.slice(0, 180) || fallback;
}
