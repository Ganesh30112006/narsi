import type { AuditAction, AuditResult } from '../types/audit';
import type { UserRole } from '../types/auth';
import type { DocumentScanStatus } from '../types/document';
import type { ConfidenceLevel, DetectionMethod, PIIType, RedactionState, RiskLevel, ValidationStatus } from '../types/finding';
import type { RedactionAction } from '../types/redaction';
import type { ReportRedactionStatus } from '../types/report';
import type { ScanStage, ScanStatus } from '../types/scan';

export const PII_TYPE_LABELS: Record<PIIType, string> = {
  AADHAAR: 'Aadhaar',
  AADHAAR_VID: 'Aadhaar VID',
  PAN: 'PAN',
  PASSPORT: 'Passport',
  DRIVING_LICENSE: 'Driving Licence',
  VOTER_ID: 'Voter ID',
  PHONE: 'Phone',
  EMAIL: 'Email',
  NAME: 'Name',
  ADDRESS: 'Address',
  DATE_OF_BIRTH: 'Date of birth',
  AADHAAR_ENROLMENT: 'Aadhaar enrolment no.',
  ROLL_NUMBER: 'Roll number',
  PLACE_OF_BIRTH: 'Place of birth',
  IDENTIFICATION_MARK: 'Identification mark',
  PHOTO: 'Photo',
  QR_CODE: 'QR code / barcode',
  SIGNATURE: 'Signature',
};

export const PII_TYPE_DESCRIPTIONS: Record<PIIType, string> = {
  AADHAAR: '12-digit unique identity number issued by UIDAI',
  AADHAAR_VID: '16-digit Virtual ID that stands in for an Aadhaar number',
  PAN: 'Permanent Account Number issued by the Income Tax Department',
  PASSPORT: 'Indian passport number',
  DRIVING_LICENSE: 'State-issued driving licence number',
  VOTER_ID: 'Electoral Photo Identity Card (EPIC) number',
  PHONE: 'Mobile or landline phone number',
  EMAIL: 'Email address',
  NAME: 'Personal name',
  ADDRESS: 'Postal or residential address',
  DATE_OF_BIRTH: 'A date identified as a date of birth',
  AADHAAR_ENROLMENT: 'Enrolment number printed on Aadhaar letters (4/5/5 digits)',
  ROLL_NUMBER: 'Examination roll, hall-ticket or seat number',
  PLACE_OF_BIRTH: 'Place of birth, as printed on passports and certificates',
  IDENTIFICATION_MARK: 'A physical identification mark (mole, scar) recorded on a certificate',
  PHOTO: 'A photo of a face, such as the holder’s portrait on an ID',
  QR_CODE: 'A QR code or barcode; the secure QR code on an Aadhaar letter encodes the holder’s details',
  SIGNATURE: 'A handwritten signature',
};

export const CONFIDENCE_LABELS: Record<ConfidenceLevel, string> = {
  HIGH: 'High confidence',
  MEDIUM: 'Medium confidence',
  LOW: 'Low confidence',
};

export const CONFIDENCE_SHORT_LABELS: Record<ConfidenceLevel, string> = {
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
  NONE: 'None',
};

export const DETECTION_METHOD_LABELS: Record<DetectionMethod, string> = {
  PATTERN: 'Pattern',
  CONTEXT: 'Context',
  CHECKSUM: 'Checksum',
  ML_MODEL: 'ML model',
  OCR: 'OCR',
  HYBRID: 'Hybrid',
  IMAGE: 'Image analysis',
};

export const VALIDATION_LABELS: Record<ValidationStatus, string> = {
  VALIDATED: 'Validated',
  UNVALIDATED: 'Not validated',
  FAILED_VALIDATION: 'Failed validation',
  NOT_APPLICABLE: 'No validation rule',
};

export const REDACTION_STATE_LABELS: Record<RedactionState, string> = {
  NONE: 'Not redacted',
  REDACTED: 'Redacted',
  MASKED: 'Masked',
  PRESERVED: 'Preserved',
};

export const REDACTION_ACTION_LABELS: Record<RedactionAction, string> = {
  REDACT: 'Redact',
  MASK: 'Mask',
  PRESERVE: 'Preserve',
};

export const REDACTION_ACTION_DESCRIPTIONS: Record<RedactionAction, string> = {
  REDACT: 'Remove the value entirely and cover it with a solid block.',
  MASK: 'Keep a few characters for reference, e.g. XXXXXX1234.',
  PRESERVE: 'Leave the value unchanged in the sanitized copy.',
};

export const REPORT_REDACTION_LABELS: Record<ReportRedactionStatus, string> = {
  NOT_REDACTED: 'Not redacted',
  PARTIALLY_REDACTED: 'Partially redacted',
  REDACTED: 'Redacted',
};

export const SCAN_STATUS_LABELS: Record<ScanStatus, string> = {
  QUEUED: 'Queued',
  PROCESSING: 'Processing',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
};

export const DOCUMENT_STATUS_LABELS: Record<DocumentScanStatus, string> = {
  NOT_SCANNED: 'Not scanned',
  QUEUED: 'Queued',
  PROCESSING: 'Processing',
  COMPLETED: 'Scanned',
  FAILED: 'Failed',
};

export const SCAN_STAGE_LABELS: Record<ScanStage, string> = {
  UPLOADED: 'Document uploaded',
  TEXT_EXTRACTION: 'Text extraction',
  OCR: 'OCR',
  NORMALIZATION: 'Normalization',
  PII_DETECTION: 'PII detection',
  VALIDATION: 'Validation',
  REPORT_GENERATION: 'Report generation',
};

export const SCAN_STAGE_DESCRIPTIONS: Record<ScanStage, string> = {
  UPLOADED: 'The file was received and stored securely.',
  TEXT_EXTRACTION: 'Reading embedded text and structure.',
  OCR: 'Recognising text in scanned pages and images.',
  NORMALIZATION: 'Cleaning whitespace, scripts and number formats.',
  PII_DETECTION: 'Matching patterns, context and models.',
  VALIDATION: 'Verifying checksums and format rules.',
  REPORT_GENERATION: 'Summarising findings for review.',
};

export const AUDIT_ACTION_LABELS: Record<AuditAction, string> = {
  LOGIN: 'Signed in',
  LOGIN_FAILED: 'Failed sign-in',
  LOGOUT: 'Signed out',
  DOCUMENT_UPLOADED: 'Uploaded document',
  SCAN_STARTED: 'Started scan',
  SCAN_COMPLETED: 'Scan completed',
  SCAN_FAILED: 'Scan failed',
  FINDINGS_VIEWED: 'Viewed findings',
  PII_REVEALED: 'Revealed a value',
  DOCUMENT_DOWNLOADED: 'Downloaded document',
  REPORT_GENERATED: 'Report generated',
  REPORT_DOWNLOADED: 'Downloaded report',
  REDACTION_CREATED: 'Created redacted copy',
  DOCUMENT_DELETED: 'Deleted document',
  SETTINGS_UPDATED: 'Updated settings',
  PASSWORD_CHANGED: 'Changed password',
  USER_CREATED: 'Created user',
  USER_UPDATED: 'Updated user',
};

export const AUDIT_RESULT_LABELS: Record<AuditResult, string> = {
  SUCCESS: 'Success',
  FAILURE: 'Failed',
  DENIED: 'Denied',
};

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Administrator',
};

const AUDIT_ROLE_LABELS: Record<string, string | undefined> = {
  admin: 'Administrator',
  public: 'Anonymous visitor',
  unknown: 'System',
};

/** Audit entries keep the role at the time of the action, including retired roles from older entries. */
export function auditRoleLabel(role: string): string {
  return AUDIT_ROLE_LABELS[role] ?? role.charAt(0).toUpperCase() + role.slice(1);
}

/** Older entries may carry actions that no longer exist (e.g. document sharing); show them readably. */
export function auditActionLabel(action: string): string {
  return (
    (AUDIT_ACTION_LABELS as Record<string, string | undefined>)[action] ??
    action.charAt(0) + action.slice(1).toLowerCase().replaceAll('_', ' ')
  );
}
