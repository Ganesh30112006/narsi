import type { PageQuery, SortOrder } from './api';

export const PII_TYPES = [
  'AADHAAR',
  'AADHAAR_VID',
  'PAN',
  'PASSPORT',
  'DRIVING_LICENSE',
  'VOTER_ID',
  'PHONE',
  'EMAIL',
  'NAME',
  'ADDRESS',
  'DATE_OF_BIRTH',
  'AADHAAR_ENROLMENT',
  'ROLL_NUMBER',
  'PLACE_OF_BIRTH',
  'IDENTIFICATION_MARK',
  'PHOTO',
  'QR_CODE',
  'SIGNATURE',
] as const;

/** Found by image analysis, not in the text: located by a box only, with nothing to reveal. */
export const VISUAL_TYPES: readonly PIIType[] = ['PHOTO', 'QR_CODE', 'SIGNATURE'];

export type PIIType = (typeof PII_TYPES)[number];

export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW';

export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';

export const DETECTION_METHODS = ['PATTERN', 'CONTEXT', 'CHECKSUM', 'ML_MODEL', 'OCR', 'HYBRID', 'IMAGE'] as const;

export type DetectionMethod = (typeof DETECTION_METHODS)[number];

export type ValidationStatus = 'VALIDATED' | 'UNVALIDATED' | 'FAILED_VALIDATION' | 'NOT_APPLICABLE';

export type RedactionState = 'NONE' | 'REDACTED' | 'MASKED' | 'PRESERVED';

/** Box normalized to the page (0–1 on each axis) so it survives zoom and rotation. */
export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FindingLocation {
  page: number | null;
  boxes: BoundingBox[];
  /** For tabular sources (XLSX/CSV). */
  sheet: string | null;
  cell: string | null;
  /** For plain text / structured sources. */
  line: number | null;
}

export interface DetectionReason {
  code: string;
  label: string;
  passed: boolean;
}

export interface Finding {
  id: string;
  scanId: string;
  documentId: string;
  documentName: string;
  piiType: PIIType;
  /** Masked by the backend. The raw value is only available through an audited reveal. */
  maskedValue: string;
  /** 0–1 */
  confidence: number;
  confidenceLevel: ConfidenceLevel;
  detectionMethod: DetectionMethod;
  /** Individual signals that contributed to a HYBRID detection. */
  detectionSignals: DetectionMethod[];
  validationStatus: ValidationStatus;
  location: FindingLocation;
  reasons: DetectionReason[];
  /** Surrounding text with the value masked, e.g. "PAN No: XXXXXX234F". */
  contextSnippet: string | null;
  redactionState: RedactionState;
  createdAt: string;
}

export type FindingSortField = 'confidence' | 'createdAt' | 'piiType' | 'page';

export interface FindingQuery extends PageQuery {
  search?: string;
  piiType?: PIIType;
  confidenceLevel?: ConfidenceLevel;
  detectionMethod?: DetectionMethod;
  documentId?: string;
  scanId?: string;
  createdFrom?: string;
  createdTo?: string;
  sortBy?: FindingSortField;
  sortOrder?: SortOrder;
}

export interface RevealRequest {
  reason: string;
}

export interface RevealedValue {
  findingId: string;
  value: string;
  /** Client re-masks the value at this time. */
  expiresAt: string;
}

export interface ConfidenceSummary {
  high: number;
  medium: number;
  low: number;
}
