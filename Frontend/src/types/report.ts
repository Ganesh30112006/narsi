import type { PageQuery } from './api';
import type { ConfidenceLevel, DetectionMethod, PIIType } from './finding';

export type ReportRedactionStatus = 'NOT_REDACTED' | 'PARTIALLY_REDACTED' | 'REDACTED';

export type ReportExportFormat = 'pdf' | 'json' | 'csv';

export interface ReportSummary {
  id: string;
  scanId: string;
  documentId: string;
  documentName: string;
  generatedAt: string;
  totalFindings: number;
  highConfidenceFindings: number;
  redactionStatus: ReportRedactionStatus;
}

export interface Report extends ReportSummary {
  scannerVersion: string;
  scanStartedAt: string | null;
  scanCompletedAt: string | null;
  pageCount: number | null;
  categories: { piiType: PIIType; count: number }[];
  confidenceDistribution: { level: ConfidenceLevel; count: number }[];
  pageDistribution: { page: number; count: number }[];
  detectionMethods: { method: DetectionMethod; count: number }[];
  ocrEngineVersion?: string | null;
  applicationVersion?: string;
  metrics?: { stageMs: Record<string, number>; totalMs: number | null; pagesProcessed: number | null; ocrUsed: boolean };
  warnings?: string[];
}

export interface ReportQuery extends PageQuery {
  search?: string;
}
