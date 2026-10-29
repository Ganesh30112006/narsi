import type { ReactNode } from 'react';
import { lazy, Suspense } from 'react';
import type { RouteObject } from 'react-router';
import { createBrowserRouter, Navigate } from 'react-router';
import { AppShell } from '../components/layout/AppShell';
import { PageSkeleton } from '../components/layout/PageSkeleton';
import type { Permission } from '../types/auth';
import { LegacyLoginRedirect, RedirectIfAuthenticated, RequireAuth, RequirePermission, Standalone } from './routeGuards';

const PublicScanPage = lazy(() => import('../pages/PublicScanPage'));
const PublicResultsPage = lazy(() => import('../pages/PublicResultsPage'));
const LoginPage = lazy(() => import('../pages/LoginPage'));
const DashboardPage = lazy(() => import('../pages/DashboardPage'));
const DocumentsPage = lazy(() => import('../pages/DocumentsPage'));
const UploadPage = lazy(() => import('../pages/UploadPage'));
const DocumentViewerPage = lazy(() => import('../pages/DocumentViewerPage'));
const ScanDetailsPage = lazy(() => import('../pages/ScanDetailsPage'));
const FindingsPage = lazy(() => import('../pages/FindingsPage'));
const ReportsPage = lazy(() => import('../pages/ReportsPage'));
const AuditLogsPage = lazy(() => import('../pages/AuditLogsPage'));
const SettingsPage = lazy(() => import('../pages/SettingsPage'));
const ProfilePage = lazy(() => import('../pages/ProfilePage'));
const NotFoundPage = lazy(() => import('../pages/NotFoundPage'));
const UnauthorizedPage = lazy(() => import('../pages/UnauthorizedPage'));

function guarded(permission: Permission, element: ReactNode) {
  return <RequirePermission permission={permission}>{element}</RequirePermission>;
}

export const routes: RouteObject[] = [
  // Public: anyone can upload a file and see its results. No account.
  {
    path: '/',
    element: (
      <Standalone>
        <PublicScanPage />
      </Standalone>
    ),
  },
  {
    path: '/results/:scanId',
    element: (
      <Standalone>
        <PublicResultsPage />
      </Standalone>
    ),
  },
  // Administrators only.
  {
    path: '/admin/login',
    element: (
      <RedirectIfAuthenticated>
        <Standalone>
          <LoginPage />
        </Standalone>
      </RedirectIfAuthenticated>
    ),
  },
  { path: '/admin', element: <Navigate to="/app/dashboard" replace /> },
  { path: '/login', element: <LegacyLoginRedirect /> },
  {
    path: '/unauthorized',
    element: (
      <RequireAuth>
        <Standalone>
          <UnauthorizedPage />
        </Standalone>
      </RequireAuth>
    ),
  },
  {
    path: '/app',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="dashboard" replace /> },
      { path: 'dashboard', element: <DashboardPage /> },
      { path: 'documents', element: guarded('documents:read', <DocumentsPage />) },
      { path: 'documents/upload', element: guarded('documents:upload', <UploadPage />) },
      { path: 'documents/:documentId', element: guarded('documents:read', <DocumentViewerPage />) },
      { path: 'scans/:scanId', element: guarded('findings:read', <ScanDetailsPage />) },
      { path: 'findings', element: guarded('findings:read', <FindingsPage />) },
      { path: 'reports', element: guarded('reports:read', <ReportsPage />) },
      { path: 'reports/:reportId', element: guarded('reports:read', <ReportsPage />) },
      { path: 'audit-logs', element: guarded('audit:read', <AuditLogsPage />) },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
  {
    path: '*',
    element: (
      <Suspense fallback={<PageSkeleton />}>
        <NotFoundPage />
      </Suspense>
    ),
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
