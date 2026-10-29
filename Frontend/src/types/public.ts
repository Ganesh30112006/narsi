import type { Finding } from './finding';
import type { Redaction } from './redaction';
import type { Scan } from './scan';

/** Returned once by `POST /public/uploads`. The token is the only key to this upload's results. */
export interface PublicUpload {
  scanId: string;
  accessToken: string;
  documentName: string;
  /** When the upload and everything derived from it is deleted automatically. */
  expiresAt: string;
}

export interface PublicFinding extends Finding {
  /**
   * The same for every occurrence of one value in this upload (an Aadhaar number printed three times shares one
   * group). Opaque, and different for every upload.
   */
  group: string;
}

export type SignatureStatus = 'VALID' | 'ALTERED' | 'UNTRUSTED' | 'INVALID';

/** One digital signature in a PDF and what checking it showed. */
export interface DocumentSignature {
  status: SignatureStatus;
  signer: string | null;
  signedAt: string | null;
  detail: string;
}

/** What the file looks like, guessed from its text. `UNKNOWN` when the model is not sure enough to say. */
export interface DocumentTypeGuess {
  label: 'AADHAAR' | 'PAN' | 'PASSPORT' | 'VOTER_ID' | 'DRIVING_LICENSE' | 'CERTIFICATE' | 'OTHER' | 'UNKNOWN';
  probability: number;
}

export interface PublicResult {
  scan: Scan;
  documentType?: DocumentTypeGuess | null;
  /** Masked values and the reasons each was flagged — never the detected values. One entry per occurrence. */
  findings: PublicFinding[];
  /** Digital signatures found in a PDF; empty when it has none (or isn't a PDF). */
  signatures: DocumentSignature[];
  /** The latest redacted copy requested for this scan, if any. */
  redaction: Redaction | null;
  reportAvailable: boolean;
  expiresAt: string;
}

export type PublicRedactionAction = 'REDACT' | 'MASK';
