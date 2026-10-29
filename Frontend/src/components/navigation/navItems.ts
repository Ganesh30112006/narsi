import type { LucideIcon } from 'lucide-react';
import { FileText, LayoutDashboard, ListChecks, ScanSearch, ScrollText, Settings, ChartNoAxesColumn } from 'lucide-react';
import type { Permission } from '../../types/auth';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  permission?: Permission;
  /** Exact match only (so /app/documents isn't active on /app/documents/upload). */
  end?: boolean;
}

export const PRIMARY_NAV: NavItem[] = [
  { to: '/app/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/app/documents', label: 'Documents', icon: FileText, end: true },
  { to: '/app/documents/upload', label: 'Scan', icon: ScanSearch, permission: 'documents:upload' },
  { to: '/app/findings', label: 'Findings', icon: ListChecks, permission: 'findings:read' },
  { to: '/app/reports', label: 'Reports', icon: ChartNoAxesColumn, permission: 'reports:read' },
  { to: '/app/audit-logs', label: 'Audit logs', icon: ScrollText, permission: 'audit:read' },
];

export const SECONDARY_NAV: NavItem[] = [{ to: '/app/settings', label: 'Settings', icon: Settings }];
