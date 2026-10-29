/**
 * Access tokens for public uploads. A token opens one upload's results and is shown only once, so it is kept
 * for this browser tab (sessionStorage): results survive a reload but not closing the tab, and other tabs,
 * windows and people can't see them. Memory is the fallback when storage is unavailable.
 */
export interface PublicAccess {
  token: string;
  documentName: string;
  expiresAt: string;
}

const PREFIX = 'govpii.public.';
const memory = new Map<string, PublicAccess>();

function isAccess(value: unknown): value is PublicAccess {
  if (typeof value !== 'object' || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.token === 'string' && typeof record.documentName === 'string' && typeof record.expiresAt === 'string';
}

export function saveAccess(scanId: string, access: PublicAccess): void {
  memory.set(scanId, access);
  try {
    window.sessionStorage.setItem(PREFIX + scanId, JSON.stringify(access));
  } catch {
    // Storage blocked (private mode, policy): the in-memory copy still works until reload.
  }
}

export function loadAccess(scanId: string): PublicAccess | null {
  const cached = memory.get(scanId);
  if (cached) return cached;
  try {
    const raw = window.sessionStorage.getItem(PREFIX + scanId);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (isAccess(parsed)) {
      memory.set(scanId, parsed);
      return parsed;
    }
  } catch {
    // Unreadable or blocked storage behaves like "no access".
  }
  return null;
}

export function forgetAccess(scanId: string): void {
  memory.delete(scanId);
  try {
    window.sessionStorage.removeItem(PREFIX + scanId);
  } catch {
    // Nothing to clean up.
  }
}
