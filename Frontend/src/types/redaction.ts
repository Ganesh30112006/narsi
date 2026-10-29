export type RedactionAction = 'REDACT' | 'MASK' | 'PRESERVE';

export type RedactionStatus = 'PROCESSING' | 'COMPLETED' | 'FAILED';

export interface RedactionItem {
  findingId: string;
  action: RedactionAction;
}

export interface RedactionRequest {
  documentId: string;
  scanId: string;
  items: RedactionItem[];
}

export interface Redaction {
  id: string;
  documentId: string;
  sourceFileName: string;
  status: RedactionStatus;
  /** Sanitized copy; the original document is never modified. */
  sanitizedDocumentId: string | null;
  sanitizedFileName: string | null;
  counts: { redacted: number; masked: number; preserved: number };
  createdAt: string;
  completedAt: string | null;
  error: string | null;
  /** True only after the sanitized copy was re-extracted and no redacted value was found. */
  verified?: boolean;
  verification?: { passed: boolean; checked: number; method: string } | null;
}
