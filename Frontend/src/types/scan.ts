import type { ConfidenceSummary, RiskLevel } from './finding';

export type ScanStatus = 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

export const SCAN_STAGES = [
  'UPLOADED',
  'TEXT_EXTRACTION',
  'OCR',
  'NORMALIZATION',
  'PII_DETECTION',
  'VALIDATION',
  'REPORT_GENERATION',
] as const;

export type ScanStage = (typeof SCAN_STAGES)[number];

export type StageState = 'PENDING' | 'ACTIVE' | 'COMPLETED' | 'SKIPPED' | 'FAILED';

export interface ScanStageProgress {
  stage: ScanStage;
  state: StageState;
  startedAt: string | null;
  completedAt: string | null;
}

export interface ScanProgress {
  currentPage: number | null;
  totalPages: number | null;
  /** 0–100 when the backend can estimate it. */
  percent: number | null;
}

export interface ScanError {
  code: string;
  /** User-safe explanation supplied by the backend. */
  message: string;
  retryable: boolean;
}

export interface Scan {
  id: string;
  documentId: string;
  documentName: string;
  status: ScanStatus;
  stages: ScanStageProgress[];
  progress: ScanProgress;
  ocrEnabled: boolean;
  scannerVersion: string;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  findingCount: number | null;
  confidenceSummary: ConfidenceSummary | null;
  reportId: string | null;
  error: ScanError | null;
  /** Non-fatal processing notes, e.g. "OCR is disabled, so text in this image was not read." */
  warnings?: string[];
  /** Pages whose text could not be read reliably (blurred, dark, grainy): nothing found there means "could not tell". */
  unreadablePages?: number[];
  ocrUsed?: boolean;
  attempt?: number;
}

/** Lightweight payload for polling `/scans/{id}/status`. */
export type ScanStatusSnapshot = Pick<Scan, 'id' | 'status' | 'stages' | 'progress' | 'error' | 'findingCount'>;

export interface CreateScanRequest {
  documentId: string;
  ocrEnabled?: boolean;
}

export interface ScanListItem {
  id: string;
  documentId: string;
  documentName: string;
  status: ScanStatus;
  findingCount: number | null;
  riskLevel: RiskLevel | null;
  createdAt: string;
  completedAt: string | null;
}
