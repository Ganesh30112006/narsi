import type { PageQuery, SortOrder } from './api';
import type { RiskLevel } from './finding';

export const DOCUMENT_FILE_TYPES = ['PDF', 'DOCX', 'XLSX', 'CSV', 'TXT', 'JSON', 'XML', 'PNG', 'JPG', 'TIFF'] as const;

export type DocumentFileType = (typeof DOCUMENT_FILE_TYPES)[number];

export type DocumentScanStatus = 'NOT_SCANNED' | 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED';

/** An original upload, or a sanitized copy produced by redaction. */
export type DocumentVariant = 'ORIGINAL' | 'SANITIZED';

export interface UserRef {
  id: string;
  name: string;
}

/** Named DocumentRecord to avoid clashing with the DOM `Document` type. */
export interface DocumentRecord {
  id: string;
  fileName: string;
  fileType: DocumentFileType;
  mimeType: string;
  sizeBytes: number;
  pageCount: number | null;
  uploadedAt: string;
  uploadedBy: UserRef;
  variant: DocumentVariant;
  /** For sanitized copies: the original document this was produced from. */
  sourceDocumentId: string | null;
  scanStatus: DocumentScanStatus;
  latestScanId: string | null;
  findingCount: number | null;
  riskLevel: RiskLevel | null;
  /** Detailed processing state (UPLOADED, EXTRACTING, DETECTING, …) from the backend. */
  status?: string;
  versionNumber?: number;
  sha256?: string;
}

export type DocumentSortField = 'fileName' | 'sizeBytes' | 'uploadedAt' | 'findingCount';

export interface DocumentQuery extends PageQuery {
  search?: string;
  fileType?: DocumentFileType;
  scanStatus?: DocumentScanStatus;
  variant?: DocumentVariant;
  uploadedFrom?: string;
  uploadedTo?: string;
  sortBy?: DocumentSortField;
  sortOrder?: SortOrder;
}

/** A rendered page of a document, used by the viewer. */
export interface DocumentPage {
  pageNumber: number;
  /** Intrinsic render size in pixels; highlights are normalized against these. */
  width: number;
  height: number;
}
