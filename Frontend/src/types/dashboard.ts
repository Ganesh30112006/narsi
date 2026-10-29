import type { AuditLog } from './audit';
import type { PIIType } from './finding';
import type { ScanListItem } from './scan';

export interface DashboardStats {
  documentsScanned: number;
  documentsWithPii: number;
  totalFindings: number;
  highConfidenceFindings: number;
  scansCompleted?: number;
  scansFailed?: number;
  /** Completed / (completed + failed); null when no scan has finished. */
  scanSuccessRate?: number | null;
  averageProcessingMs?: number | null;
}

export interface DashboardSummary {
  stats: DashboardStats;
  piiDistribution: { piiType: PIIType; count: number }[];
  recentScans: ScanListItem[];
  recentActivity: AuditLog[];
}
