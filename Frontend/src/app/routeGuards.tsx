import type { ReactNode } from 'react';
import { Suspense, useEffect } from 'react';
import { Navigate, useLocation, useSearchParams } from 'react-router';
import { LogoMark } from '../components/brand/Logo';
import { Spinner } from '../components/ui/Spinner';
import { useAuth } from '../hooks/useAuth';
import type { Permission } from '../types/auth';
import { safeRedirectPath } from '../utils/security';
import styles from './routeGuards.module.css';

function SessionRestoring() {
  return (
    <div className={styles.restoring}>
      <LogoMark size={32} />
      <Spinner size={16} label="Restoring your session" />
    </div>
  );
}

/** Starts the one-time session check and reports whether it is still running. */
function useRestoredSession() {
  const { status, restore } = useAuth();
  useEffect(() => restore(), [restore]);
  return { status, pending: status === 'idle' || status === 'restoring' };
}

/** Requires an administrator session; otherwise redirects to the admin sign-in and remembers the destination. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, pending } = useRestoredSession();
  const location = useLocation();
  if (pending) return <SessionRestoring />;
  if (status === 'anonymous') {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/admin/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children}</>;
}

/** Signed-in administrators visiting the sign-in page go on to their destination (`?next=`) or the dashboard. */
export function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const { status, pending } = useRestoredSession();
  const [params] = useSearchParams();
  if (pending) return <SessionRestoring />;
  if (status === 'authenticated') return <Navigate to={safeRedirectPath(params.get('next'))} replace />;
  return <>{children}</>;
}

/** Role-based route protection. The backend enforces the same rules on every request. */
export function RequirePermission({ permission, children }: { permission: Permission; children: ReactNode }) {
  const { can } = useAuth();
  const location = useLocation();
  if (!can(permission)) return <Navigate to="/unauthorized" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/** Suspense boundary for routes rendered outside the app shell. */
export function Standalone({ children }: { children: ReactNode }) {
  return <Suspense fallback={<SessionRestoring />}>{children}</Suspense>;
}

/** Old sign-in links keep working (including `?next=`). */
export function LegacyLoginRedirect() {
  const { search } = useLocation();
  return <Navigate to={`/admin/login${search}`} replace />;
}
