/**
 * Mock-only in-memory database. All values here are synthetic and never ship in production builds.
 */
import type { ApiKey } from '../types/apiKey';
import type { AuditAction, AuditLog, AuditResult } from '../types/audit';
import type { SessionInfo, User, UserRole } from '../types/auth';
import type { DocumentFileType, DocumentRecord } from '../types/document';
import type {
  ConfidenceLevel,
  DetectionMethod,
  DetectionReason,
  Finding,
  PIIType,
  RiskLevel,
  ValidationStatus,
} from '../types/finding';
import type { Redaction, RedactionAction } from '../types/redaction';
import type { Report } from '../types/report';
import type { Scan, ScanStage, ScanStageProgress } from '../types/scan';
import { SCAN_STAGES } from '../types/scan';
import type { ScanSettings } from '../types/settings';
import { maskValue } from '../utils/security';
import type { MockLine, MockPageContent } from './mockPages';
import { boxesForKey } from './mockPages';

export const MOCK_PASSWORD = 'GuardDemo#2026';
export const SCANNER_VERSION = 'govpii-scanner 2.4.1';

// ---------------------------------------------------------------------------
// Deterministic randomness
// ---------------------------------------------------------------------------

export function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function createRng(seed: number) {
  let state = seed || 1;
  const next = () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return {
    next,
    int: (min: number, max: number) => Math.floor(next() * (max - min + 1)) + min,
    pick: <T>(items: readonly T[]): T => items[Math.floor(next() * items.length)] as T,
    range: (min: number, max: number) => min + next() * (max - min),
  };
}

type Rng = ReturnType<typeof createRng>;

// ---------------------------------------------------------------------------
// Synthetic values (formats only — not real identities)
// ---------------------------------------------------------------------------

const FIRST_NAMES = [
  'Rohan',
  'Meera',
  'Arjun',
  'Kavya',
  'Imran',
  'Sneha',
  'Rahul',
  'Farah',
  'Aditya',
  'Lakshmi',
  'Devika',
  'Sanjay',
];
const LAST_NAMES = ['Kumar', 'Iyer', 'Sharma', 'Nair', 'Khan', 'Reddy', 'Patel', 'Das', 'Joshi', 'Menon', 'Gupta', 'Bose'];
const STREETS = ['2nd Cross, Indiranagar', 'MG Road', 'Park Street', 'Linking Road, Bandra', 'Anna Salai', 'Sector 21'];
const CITIES = ['Bengaluru 560038', 'Kolkata 700016', 'Mumbai 400050', 'Chennai 600002', 'Noida 201301', 'Pune 411001'];
const LETTERS = 'ABCDEFGHJKLMNPRSTUVWXYZ';

function letters(rng: Rng, count: number) {
  return Array.from({ length: count }, () => rng.pick(LETTERS.split(''))).join('');
}
function digits(rng: Rng, count: number) {
  return Array.from({ length: count }, () => String(rng.int(0, 9))).join('');
}

export function syntheticValue(type: PIIType, rng: Rng): string {
  switch (type) {
    case 'AADHAAR':
      return `${rng.int(2, 9)}${digits(rng, 3)} ${digits(rng, 4)} ${digits(rng, 4)}`;
    case 'AADHAAR_VID':
      return `${rng.int(1, 9)}${digits(rng, 3)} ${digits(rng, 4)} ${digits(rng, 4)} ${digits(rng, 4)}`;
    case 'PAN':
      return `${letters(rng, 3)}P${letters(rng, 1)}${digits(rng, 4)}${letters(rng, 1)}`;
    case 'PASSPORT':
      return `${letters(rng, 1)}${digits(rng, 7)}`;
    case 'DRIVING_LICENSE':
      return `${rng.pick(['MH', 'KA', 'DL', 'TN', 'WB'])}${digits(rng, 2)} ${rng.int(2008, 2022)}${digits(rng, 7)}`;
    case 'VOTER_ID':
      return `${letters(rng, 3)}${digits(rng, 7)}`;
    case 'PHONE':
      return `+91 ${rng.int(7, 9)}${digits(rng, 4)} ${digits(rng, 5)}`;
    case 'EMAIL':
      return `${rng.pick(FIRST_NAMES).toLowerCase()}.${rng.pick(LAST_NAMES).toLowerCase()}@example.in`;
    case 'NAME':
      return `${rng.pick(FIRST_NAMES)} ${rng.pick(LAST_NAMES)}`;
    case 'ADDRESS':
      return `${rng.int(3, 220)}, ${rng.pick(STREETS)}, ${rng.pick(CITIES)}`;
    case 'AADHAAR_ENROLMENT':
      return `${digits(rng, 4)}/${digits(rng, 5)}/${digits(rng, 5)}`;
    case 'ROLL_NUMBER':
      return digits(rng, 10);
    case 'PLACE_OF_BIRTH':
      return (rng.pick(CITIES).split(' ')[0] ?? 'PUNE').toUpperCase();
    case 'IDENTIFICATION_MARK':
      return rng.pick(['A mole on the left hand', 'A scar on the right knee', 'A mole on the neck']);
    case 'PHOTO':
    case 'QR_CODE':
    case 'SIGNATURE':
      return ''; // visual findings have no text value
    case 'DATE_OF_BIRTH':
      return `${String(rng.int(1, 28)).padStart(2, '0')}/${String(rng.int(1, 12)).padStart(2, '0')}/${rng.int(1955, 2004)}`;
  }
}

const FIELD_LABELS: Record<PIIType, string[]> = {
  AADHAAR: ['Aadhaar No.', 'Aadhaar number', 'UID'],
  AADHAAR_VID: ['VID', 'Virtual ID'],
  PAN: ['PAN', 'PAN No.', 'Permanent Account No.'],
  PASSPORT: ['Passport No.', 'Passport number'],
  DRIVING_LICENSE: ['Driving Licence No.', 'DL number'],
  VOTER_ID: ['Voter ID (EPIC)', 'EPIC No.'],
  PHONE: ['Mobile', 'Contact number', 'Phone'],
  EMAIL: ['Email', 'Email address'],
  NAME: ['Full name', 'Applicant name', 'Employee name'],
  ADDRESS: ['Residential address', 'Address', 'Permanent address'],
  DATE_OF_BIRTH: ['Date of birth', 'DOB'],
  AADHAAR_ENROLMENT: ['Enrolment No.'],
  ROLL_NUMBER: ['Roll No.', 'Hall Ticket No.'],
  PLACE_OF_BIRTH: ['Place of Birth'],
  IDENTIFICATION_MARK: ['Marks of Identification'],
  PHOTO: ['Photo'],
  QR_CODE: ['QR code'],
  SIGNATURE: ['Signature'],
};

const FILLER_TEXT = [
  'The applicant confirms the information provided is accurate.',
  'This record is maintained under the organisation’s records policy.',
  'Please retain a copy of this form for your reference.',
  'Supporting documents were verified by the reviewing officer.',
  'Any changes must be reported within thirty days.',
];

// ---------------------------------------------------------------------------
// Detection simulation
// ---------------------------------------------------------------------------

interface DetectionProfile {
  confidence: [number, number];
  method: DetectionMethod;
  signals: DetectionMethod[];
  reasons: (labelNearby: boolean, validated: boolean) => DetectionReason[];
  validates: boolean;
}

const DETECTION: Record<PIIType, DetectionProfile> = {
  DATE_OF_BIRTH: {
    confidence: [0.9, 0.98],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: 'Matches the expected calendar date', passed: true },
      { code: 'CONTEXT', label: 'Nearby date-of-birth label', passed: label },
      { code: 'DOB_PLAUSIBLE_AGE', label: 'Implies a plausible age (0–120 years)', passed: valid },
    ],
  },
  AADHAAR: {
    confidence: [0.9, 0.99],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT', 'CHECKSUM'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: '12-digit Aadhaar format matched', passed: true },
      { code: 'CONTEXT', label: 'Nearby Aadhaar label', passed: label },
      { code: 'CHECKSUM', label: 'Verhoeff checksum passed', passed: valid },
    ],
  },
  AADHAAR_VID: {
    confidence: [0.88, 0.97],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT', 'CHECKSUM'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: '16-digit Aadhaar Virtual ID format matched', passed: true },
      { code: 'CONTEXT', label: 'Nearby VID label', passed: label },
      { code: 'CHECKSUM', label: 'Verhoeff checksum passed', passed: valid },
    ],
  },
  AADHAAR_ENROLMENT: {
    confidence: [0.85, 0.95],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: 'Aadhaar enrolment number layout (4/5/5 digits)', passed: true },
      { code: 'CONTEXT', label: 'Nearby enrolment label', passed: label },
      { code: 'EID_STRUCTURE', label: '14 digits in the 4/5/5 enrolment number layout', passed: valid },
    ],
  },
  ROLL_NUMBER: {
    confidence: [0.85, 0.95],
    method: 'CONTEXT',
    signals: ['CONTEXT'],
    validates: false,
    reasons: (labelNearby) => [
      { code: 'FORMAT', label: 'Roll number shape', passed: true },
      { code: 'CONTEXT', label: 'Nearby roll number label', passed: labelNearby },
    ],
  },
  PLACE_OF_BIRTH: {
    confidence: [0.85, 0.95],
    method: 'CONTEXT',
    signals: ['CONTEXT'],
    validates: false,
    reasons: (labelNearby) => [
      { code: 'FORMAT', label: 'Place name', passed: true },
      { code: 'CONTEXT', label: 'Nearby place-of-birth label', passed: labelNearby },
    ],
  },
  IDENTIFICATION_MARK: {
    confidence: [0.85, 0.95],
    method: 'CONTEXT',
    signals: ['CONTEXT'],
    validates: false,
    reasons: (labelNearby) => [
      { code: 'FORMAT', label: 'Identification mark description', passed: true },
      { code: 'CONTEXT', label: 'Nearby identification-mark label', passed: labelNearby },
    ],
  },
  PHOTO: {
    confidence: [0.9, 0.9],
    method: 'IMAGE',
    signals: ['IMAGE'],
    validates: false,
    reasons: () => [{ code: 'VISUAL_FACE', label: 'A face photo (two face detectors agree)', passed: true }],
  },
  QR_CODE: {
    confidence: [0.88, 0.95],
    method: 'IMAGE',
    signals: ['IMAGE'],
    validates: false,
    reasons: () => [
      { code: 'VISUAL_QR', label: 'A QR code, which can encode personal details (location only, not decoded)', passed: true },
    ],
  },
  SIGNATURE: {
    confidence: [0.7, 0.75],
    method: 'IMAGE',
    signals: ['IMAGE'],
    validates: false,
    reasons: () => [{ code: 'VISUAL_SIGNATURE', label: 'Handwritten strokes next to a “Signature” label', passed: true }],
  },
  PAN: {
    confidence: [0.88, 0.98],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT', 'CHECKSUM'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: 'Format matched (AAAAA9999A)', passed: true },
      { code: 'CONTEXT', label: 'Nearby PAN label', passed: label },
      { code: 'STRUCTURE', label: 'Holder-type character is valid', passed: valid },
    ],
  },
  PASSPORT: {
    confidence: [0.78, 0.93],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: 'Passport number format matched', passed: true },
      { code: 'CONTEXT', label: 'Nearby passport label', passed: label },
      { code: 'STRUCTURE', label: 'Series letter is valid', passed: valid },
    ],
  },
  DRIVING_LICENSE: {
    confidence: [0.7, 0.9],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: 'State code and number format matched', passed: true },
      { code: 'CONTEXT', label: 'Nearby licence label', passed: label },
      { code: 'STRUCTURE', label: 'Issue year is plausible', passed: valid },
    ],
  },
  VOTER_ID: {
    confidence: [0.72, 0.9],
    method: 'HYBRID',
    signals: ['PATTERN', 'CONTEXT'],
    validates: false,
    reasons: (label) => [
      { code: 'FORMAT', label: 'EPIC format matched (AAA9999999)', passed: true },
      { code: 'CONTEXT', label: 'Nearby voter ID label', passed: label },
    ],
  },
  PHONE: {
    confidence: [0.8, 0.95],
    method: 'PATTERN',
    signals: ['PATTERN'],
    validates: true,
    reasons: (label, valid) => [
      { code: 'FORMAT', label: 'Indian mobile number format matched', passed: true },
      { code: 'CONTEXT', label: 'Nearby contact label', passed: label },
      { code: 'PREFIX', label: 'Valid mobile prefix', passed: valid },
    ],
  },
  EMAIL: {
    confidence: [0.96, 0.99],
    method: 'PATTERN',
    signals: ['PATTERN'],
    validates: true,
    reasons: (_label, valid) => [
      { code: 'FORMAT', label: 'Email address format matched', passed: true },
      { code: 'DOMAIN', label: 'Domain is well-formed', passed: valid },
    ],
  },
  NAME: {
    confidence: [0.52, 0.82],
    method: 'ML_MODEL',
    signals: ['ML_MODEL', 'CONTEXT'],
    validates: false,
    reasons: (label) => [
      { code: 'NER', label: 'Recognised as a person name by the language model', passed: true },
      { code: 'CONTEXT', label: 'Nearby name label', passed: label },
    ],
  },
  ADDRESS: {
    confidence: [0.6, 0.86],
    method: 'HYBRID',
    signals: ['ML_MODEL', 'CONTEXT', 'PATTERN'],
    validates: false,
    reasons: (label) => [
      { code: 'NER', label: 'Recognised as a location by the language model', passed: true },
      { code: 'PIN', label: '6-digit PIN code present', passed: true },
      { code: 'CONTEXT', label: 'Nearby address label', passed: label },
    ],
  },
};

export function confidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.9) return 'HIGH';
  if (confidence >= 0.7) return 'MEDIUM';
  return 'LOW';
}

export function riskFromFindings(findings: Pick<Finding, 'confidenceLevel' | 'piiType'>[]): RiskLevel {
  if (findings.length === 0) return 'NONE';
  const governmentIds: PIIType[] = ['AADHAAR', 'PAN', 'PASSPORT', 'DRIVING_LICENSE', 'VOTER_ID'];
  if (findings.some((finding) => finding.confidenceLevel === 'HIGH' && governmentIds.includes(finding.piiType))) return 'HIGH';
  if (findings.some((finding) => finding.confidenceLevel !== 'LOW')) return 'MEDIUM';
  return 'LOW';
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export interface MockUser extends User {
  password: string;
}

/** Who an audit entry is attributed to: an administrator, the public upload account, or the system. */
export interface AuditActor {
  id: string | null;
  name: string;
  role: AuditLog['user']['role'];
}

/** Owns anonymous uploads from the public scan page. It is not an account and can never sign in. */
export const PUBLIC_ACTOR: AuditActor & { id: string } = { id: 'usr_public', name: 'Public upload', role: 'public' };

export interface MockDocument extends DocumentRecord {
  content: MockPageContent[];
  /** Set for anonymous public uploads: the only key to their results. */
  publicToken?: string;
  /** Applied when rendering a sanitized copy. */
  redactions: Record<string, RedactionAction>;
}

export interface MockScan extends Scan {
  startedAtMs: number;
  /** Stage durations in ms, simulated. */
  durations: number[];
  failAt: ScanStage | null;
  materialized: boolean;
}

export interface MockState {
  users: MockUser[];
  documents: MockDocument[];
  scans: MockScan[];
  findings: (Finding & { fieldKey: string; rawValue: string })[];
  reports: Report[];
  redactions: Redaction[];
  auditLogs: AuditLog[];
  sessions: SessionInfo[];
  apiKeys: (ApiKey & { userId: string })[];
  settings: ScanSettings;
  sessionUserId: string | null;
  failedLogins: number;
  seq: number;
}

const DAY = 24 * 3600 * 1000;

function iso(ms: number) {
  return new Date(ms).toISOString();
}

export function nextId(state: MockState, prefix: string) {
  state.seq += 1;
  return `${prefix}_${state.seq.toString(36).padStart(5, '0')}`;
}

const MIME_BY_TYPE: Record<DocumentFileType, string> = {
  PDF: 'application/pdf',
  DOCX: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  XLSX: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  CSV: 'text/csv',
  TXT: 'text/plain',
  JSON: 'application/json',
  XML: 'application/xml',
  PNG: 'image/png',
  JPG: 'image/jpeg',
  TIFF: 'image/tiff',
};

export function mimeFor(type: DocumentFileType) {
  return MIME_BY_TYPE[type];
}

function titleFromFileName(fileName: string) {
  const base = fileName.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
  return base.charAt(0).toUpperCase() + base.slice(1);
}

/** Builds synthetic page content with the requested PII placed on each page. */
export function buildContent(fileName: string, plan: PIIType[][]): MockPageContent[] {
  const rng = createRng(hashString(fileName));
  const title = titleFromFileName(fileName);
  return plan.map((types, pageIndex) => {
    const lines: MockLine[] = [];
    if (pageIndex === 0) {
      lines.push({ kind: 'title', text: title });
      lines.push({ kind: 'subtitle', text: `Reference ${letters(rng, 2)}-${digits(rng, 6)} · Internal` });
    } else {
      lines.push({ kind: 'heading', text: `Section ${pageIndex + 1}` });
    }
    lines.push({ kind: 'rule' });
    lines.push({ kind: 'text', text: rng.pick(FILLER_TEXT) });
    lines.push({
      kind: 'field',
      label: 'Date',
      value: `${rng.int(1, 28)}/0${rng.int(1, 9)}/2026`,
      piiType: null,
      key: `p${pageIndex}-date`,
    });
    types.forEach((type, index) => {
      lines.push({
        kind: 'field',
        label: rng.pick(FIELD_LABELS[type]),
        value: syntheticValue(type, rng),
        piiType: type,
        key: `p${pageIndex}-f${index}`,
      });
      if (index % 3 === 2) lines.push({ kind: 'text', text: rng.pick(FILLER_TEXT) });
    });
    lines.push({
      kind: 'field',
      label: 'Department',
      value: rng.pick(['Human Resources', 'Finance', 'Procurement', 'Legal']),
      piiType: null,
      key: `p${pageIndex}-dept`,
    });
    lines.push({ kind: 'rule' });
    lines.push({ kind: 'text', text: rng.pick(FILLER_TEXT) });
    return { lines };
  });
}

export function buildFindings(state: MockState, document: MockDocument, scan: Scan, createdAtMs: number) {
  const rng = createRng(hashString(`${document.id}:${scan.id}`));
  const findings: MockState['findings'] = [];
  document.content.forEach((page, pageIndex) => {
    page.lines.forEach((line, lineIndex) => {
      if (line.kind !== 'field' || !line.piiType) return;
      const profile = DETECTION[line.piiType];
      const location = boxesForKey(document.content, line.key);
      const previous = page.lines[lineIndex - 1];
      const labelNearby = previous?.kind !== 'text' || rng.next() > 0.3;
      const validated = !profile.validates || rng.next() > 0.12;
      let confidence = rng.range(profile.confidence[0], profile.confidence[1]);
      if (!validated) confidence = Math.max(0.45, confidence - 0.3);
      if (!labelNearby) confidence = Math.max(0.4, confidence - 0.12);
      const signals =
        document.fileType === 'PNG' || document.fileType === 'JPG' || document.fileType === 'TIFF'
          ? ['OCR' as const, ...profile.signals]
          : profile.signals;
      const validationStatus: ValidationStatus = !profile.validates
        ? 'NOT_APPLICABLE'
        : validated
          ? 'VALIDATED'
          : 'FAILED_VALIDATION';
      const masked = maskValue(line.value, line.piiType);
      findings.push({
        id: nextId(state, 'fnd'),
        scanId: scan.id,
        documentId: document.id,
        documentName: document.fileName,
        piiType: line.piiType,
        maskedValue: masked,
        rawValue: line.value,
        fieldKey: line.key,
        confidence: Math.round(confidence * 100) / 100,
        confidenceLevel: confidenceLevel(confidence),
        detectionMethod: profile.method,
        detectionSignals: signals,
        validationStatus,
        location: {
          page: location?.page ?? pageIndex + 1,
          boxes: location ? [location.box] : [],
          sheet: document.fileType === 'XLSX' ? `Sheet${pageIndex + 1}` : null,
          cell: document.fileType === 'XLSX' || document.fileType === 'CSV' ? `C${lineIndex + 2}` : null,
          line: ['TXT', 'JSON', 'XML', 'CSV'].includes(document.fileType) ? lineIndex + 1 : null,
        },
        reasons: profile.reasons(labelNearby, validated),
        contextSnippet: `${line.label}: ${masked}`,
        redactionState: 'NONE',
        createdAt: iso(createdAtMs),
      });
    });
  });
  return findings;
}

export function buildReport(scan: Scan, document: MockDocument, findings: Finding[]): Report {
  const count = <K extends string>(keys: K[]) => {
    const map = new Map<K, number>();
    keys.forEach((key) => map.set(key, (map.get(key) ?? 0) + 1));
    return map;
  };
  const byType = count(findings.map((finding) => finding.piiType));
  const byLevel = count(findings.map((finding) => finding.confidenceLevel));
  const byMethod = count(findings.map((finding) => finding.detectionMethod));
  const byPage = count(findings.map((finding) => String(finding.location.page ?? 0)));
  return {
    id: `rpt_${scan.id}`,
    scanId: scan.id,
    documentId: document.id,
    documentName: document.fileName,
    generatedAt: scan.completedAt ?? iso(Date.now()),
    totalFindings: findings.length,
    highConfidenceFindings: byLevel.get('HIGH') ?? 0,
    redactionStatus: 'NOT_REDACTED',
    scannerVersion: scan.scannerVersion,
    scanStartedAt: scan.startedAt,
    scanCompletedAt: scan.completedAt,
    pageCount: document.pageCount,
    categories: [...byType.entries()].map(([piiType, value]) => ({ piiType, count: value })).sort((a, b) => b.count - a.count),
    confidenceDistribution: (['HIGH', 'MEDIUM', 'LOW'] as const).map((level) => ({ level, count: byLevel.get(level) ?? 0 })),
    pageDistribution: Array.from({ length: document.pageCount ?? 1 }, (_, index) => ({
      page: index + 1,
      count: byPage.get(String(index + 1)) ?? 0,
    })),
    detectionMethods: [...byMethod.entries()].map(([method, value]) => ({ method, count: value })),
  };
}

export function stageDurations(pageCount: number, ocr: boolean): number[] {
  return SCAN_STAGES.map((stage) => {
    switch (stage) {
      case 'UPLOADED':
        return 500;
      case 'TEXT_EXTRACTION':
        return 900 + pageCount * 250;
      case 'OCR':
        return ocr ? 700 + pageCount * 650 : 0;
      case 'NORMALIZATION':
        return 700;
      case 'PII_DETECTION':
        return 1200 + pageCount * 300;
      case 'VALIDATION':
        return 900;
      case 'REPORT_GENERATION':
        return 700;
    }
  });
}

export function completedStages(scan: Pick<Scan, 'ocrEnabled'>, startedAtMs: number, durations: number[]): ScanStageProgress[] {
  let cursor = startedAtMs;
  return SCAN_STAGES.map((stage, index) => {
    const duration = durations[index] ?? 0;
    const skipped = stage === 'OCR' && (!scan.ocrEnabled || duration === 0);
    const startedAt = iso(cursor);
    cursor += duration;
    return {
      stage,
      state: skipped ? 'SKIPPED' : 'COMPLETED',
      startedAt: skipped ? null : startedAt,
      completedAt: skipped ? null : iso(cursor),
    };
  });
}

export function addAudit(
  state: MockState,
  entry: {
    action: AuditAction;
    user: AuditActor;
    document?: DocumentRecord | null;
    result?: AuditResult;
    details?: string | null;
    at?: number;
  },
) {
  state.auditLogs.unshift({
    id: nextId(state, 'aud'),
    timestamp: iso(entry.at ?? Date.now()),
    user: { id: entry.user.id, name: entry.user.name, role: entry.user.role },
    action: entry.action,
    documentId: entry.document?.id ?? null,
    documentName: entry.document?.fileName ?? null,
    result: entry.result ?? 'SUCCESS',
    details: entry.details ?? null,
  });
}

// ---------------------------------------------------------------------------
// Seed
// ---------------------------------------------------------------------------

interface SeedDocument {
  fileName: string;
  type: DocumentFileType;
  plan: PIIType[][];
  daysAgo: number;
  status: 'COMPLETED' | 'FAILED' | 'NOT_SCANNED';
  sizeKb: number;
}

const SEED_DOCUMENTS: SeedDocument[] = [
  {
    fileName: 'employee_application.pdf',
    type: 'PDF',
    daysAgo: 0.1,
    status: 'COMPLETED',
    sizeKb: 842,
    plan: [['NAME', 'PAN', 'AADHAAR', 'PHONE'], ['ADDRESS', 'PASSPORT', 'EMAIL'], []],
  },
  {
    fileName: 'vendor_kyc_register.xlsx',
    type: 'XLSX',
    daysAgo: 0.4,
    status: 'COMPLETED',
    sizeKb: 356,
    plan: [
      ['NAME', 'PAN', 'PHONE', 'NAME', 'PAN'],
      ['NAME', 'PAN', 'EMAIL'],
    ],
  },
  {
    fileName: 'tenant_verification_form.pdf',
    type: 'PDF',
    daysAgo: 1.2,
    status: 'COMPLETED',
    sizeKb: 1210,
    plan: [['NAME', 'AADHAAR', 'VOTER_ID'], ['ADDRESS', 'PHONE'], ['NAME']],
  },
  {
    fileName: 'passport_scan_0419.jpg',
    type: 'JPG',
    daysAgo: 1.6,
    status: 'COMPLETED',
    sizeKb: 2310,
    plan: [['NAME', 'PASSPORT', 'ADDRESS']],
  },
  {
    fileName: 'payroll_march_2026.csv',
    type: 'CSV',
    daysAgo: 2.3,
    status: 'COMPLETED',
    sizeKb: 188,
    plan: [['NAME', 'PAN', 'NAME', 'PAN', 'NAME', 'PAN']],
  },
  {
    fileName: 'loan_agreement_draft.docx',
    type: 'DOCX',
    daysAgo: 3.1,
    status: 'COMPLETED',
    sizeKb: 96,
    plan: [['NAME', 'ADDRESS'], ['PAN', 'AADHAAR'], ['PHONE', 'EMAIL'], []],
  },
  { fileName: 'board_minutes_q2.pdf', type: 'PDF', daysAgo: 3.8, status: 'COMPLETED', sizeKb: 402, plan: [[], []] },
  {
    fileName: 'driver_onboarding_batch.pdf',
    type: 'PDF',
    daysAgo: 4.5,
    status: 'COMPLETED',
    sizeKb: 3120,
    plan: [
      ['NAME', 'DRIVING_LICENSE', 'PHONE'],
      ['NAME', 'DRIVING_LICENSE', 'AADHAAR'],
      ['NAME', 'DRIVING_LICENSE'],
    ],
  },
  {
    fileName: 'customer_export.json',
    type: 'JSON',
    daysAgo: 5.2,
    status: 'COMPLETED',
    sizeKb: 74,
    plan: [['NAME', 'EMAIL', 'PHONE', 'NAME', 'EMAIL']],
  },
  { fileName: 'archived_forms_1998.tiff', type: 'TIFF', daysAgo: 6, status: 'FAILED', sizeKb: 8840, plan: [['NAME', 'ADDRESS']] },
  {
    fileName: 'grievance_letters.txt',
    type: 'TXT',
    daysAgo: 6.7,
    status: 'COMPLETED',
    sizeKb: 22,
    plan: [['NAME', 'PHONE', 'ADDRESS']],
  },
  {
    fileName: 'hr_records_export.xml',
    type: 'XML',
    daysAgo: 7.4,
    status: 'COMPLETED',
    sizeKb: 130,
    plan: [
      ['NAME', 'PAN', 'AADHAAR', 'EMAIL'],
      ['NAME', 'PASSPORT'],
    ],
  },
  { fileName: 'public_notice_tender.pdf', type: 'PDF', daysAgo: 8.9, status: 'COMPLETED', sizeKb: 210, plan: [[]] },
  { fileName: 'id_card_front.png', type: 'PNG', daysAgo: 9.5, status: 'COMPLETED', sizeKb: 1480, plan: [['NAME', 'VOTER_ID']] },
  {
    fileName: 'scholarship_applications.xlsx',
    type: 'XLSX',
    daysAgo: 11,
    status: 'NOT_SCANNED',
    sizeKb: 512,
    plan: [
      ['NAME', 'AADHAAR', 'PHONE'],
      ['NAME', 'AADHAAR'],
    ],
  },
  {
    fileName: 'field_survey_notes.docx',
    type: 'DOCX',
    daysAgo: 12.5,
    status: 'NOT_SCANNED',
    sizeKb: 64,
    plan: [['ADDRESS', 'PHONE']],
  },
];

function seedUsers(): MockUser[] {
  const created = iso(Date.now() - 180 * DAY);
  const users: [string, string, string, UserRole][] = [['usr_admin', 'Ananya Rao', 'admin', 'admin']];
  return users.map(([id, name, username, role]) => ({
    id,
    name,
    role,
    username,
    password: MOCK_PASSWORD,
    createdAt: created,
    lastLoginAt: iso(Date.now() - 2 * DAY),
  }));
}

export function createSeedState(): MockState {
  const now = Date.now();
  const state: MockState = {
    users: seedUsers(),
    documents: [],
    scans: [],
    findings: [],
    reports: [],
    redactions: [],
    auditLogs: [],
    apiKeys: [],
    sessions: [
      {
        id: 'ses_current',
        device: 'Chrome on Windows',
        location: 'Bengaluru, IN',
        createdAt: iso(now - 3600 * 1000),
        lastActiveAt: iso(now),
        current: true,
      },
      {
        id: 'ses_2',
        device: 'Firefox on Ubuntu',
        location: 'Bengaluru, IN',
        createdAt: iso(now - 3 * DAY),
        lastActiveAt: iso(now - DAY),
        current: false,
      },
      {
        id: 'ses_3',
        device: 'Safari on iPad',
        location: 'Mumbai, IN',
        createdAt: iso(now - 9 * DAY),
        lastActiveAt: iso(now - 5 * DAY),
        current: false,
      },
    ],
    settings: {
      ocrEnabled: true,
      confidenceThreshold: 0.5,
      defaultRedactionMode: 'REDACT',
      retentionDays: 90,
      autoDeleteEnabled: false,
    },
    sessionUserId: null,
    failedLogins: 0,
    seq: 100,
  };

  const [admin] = state.users as [MockUser];

  // Oldest first so audit log order is natural.
  [...SEED_DOCUMENTS].reverse().forEach((seed, index) => {
    // Most files arrive through the public scan page; administrators upload some themselves.
    const uploader: AuditActor & { id: string } = index % 3 === 0 ? admin : PUBLIC_ACTOR;
    const uploadedMs = now - seed.daysAgo * DAY;
    const document: MockDocument = {
      id: `doc_${hashString(seed.fileName).toString(36)}`,
      fileName: seed.fileName,
      fileType: seed.type,
      mimeType: mimeFor(seed.type),
      sizeBytes: seed.sizeKb * 1024 + (hashString(seed.fileName) % 1000),
      pageCount: seed.plan.length,
      uploadedAt: iso(uploadedMs),
      uploadedBy: { id: uploader.id, name: uploader.name },
      variant: 'ORIGINAL',
      sourceDocumentId: null,
      scanStatus: 'NOT_SCANNED',
      latestScanId: null,
      findingCount: null,
      riskLevel: null,
      content: buildContent(seed.fileName, seed.plan),
      redactions: {},
    };
    state.documents.unshift(document);
    addAudit(state, { action: 'DOCUMENT_UPLOADED', user: uploader, document, at: uploadedMs });

    if (seed.status === 'NOT_SCANNED') return;

    const ocr = ['PNG', 'JPG', 'TIFF'].includes(seed.type) || seed.fileName.includes('application');
    const durations = stageDurations(seed.plan.length, ocr);
    const startedMs = uploadedMs + 5000;
    const total = durations.reduce((sum, value) => sum + value, 0);
    const scan: MockScan = {
      id: `scn_${hashString(`scan:${seed.fileName}`).toString(36)}`,
      documentId: document.id,
      documentName: document.fileName,
      status: 'COMPLETED',
      stages: completedStages({ ocrEnabled: ocr }, startedMs, durations),
      progress: { currentPage: seed.plan.length, totalPages: seed.plan.length, percent: 100 },
      ocrEnabled: ocr,
      scannerVersion: SCANNER_VERSION,
      createdAt: iso(startedMs),
      startedAt: iso(startedMs),
      completedAt: iso(startedMs + total),
      findingCount: null,
      confidenceSummary: null,
      reportId: null,
      error: null,
      startedAtMs: startedMs,
      durations,
      failAt: null,
      materialized: true,
    };
    addAudit(state, { action: 'SCAN_STARTED', user: uploader, document, at: startedMs });

    if (seed.status === 'FAILED') {
      scan.status = 'FAILED';
      scan.stages = scan.stages.map((stage, stageIndex) =>
        stageIndex < 2
          ? stage
          : stageIndex === 2
            ? { ...stage, state: 'FAILED', completedAt: null }
            : { stage: stage.stage, state: 'PENDING', startedAt: null, completedAt: null },
      );
      scan.completedAt = null;
      scan.progress = { currentPage: 1, totalPages: seed.plan.length, percent: 30 };
      scan.error = {
        code: 'OCR_UNREADABLE',
        message: 'Text on these pages could not be recognised. The scan may be too faint or low resolution.',
        retryable: true,
      };
      document.scanStatus = 'FAILED';
      document.latestScanId = scan.id;
      state.scans.unshift(scan);
      addAudit(state, {
        action: 'SCAN_FAILED',
        user: uploader,
        document,
        result: 'FAILURE',
        details: 'OCR could not read the document',
        at: startedMs + 4000,
      });
      return;
    }

    const findings = buildFindings(state, document, scan, startedMs + total);
    state.findings.push(...findings);
    const summary = {
      high: findings.filter((finding) => finding.confidenceLevel === 'HIGH').length,
      medium: findings.filter((finding) => finding.confidenceLevel === 'MEDIUM').length,
      low: findings.filter((finding) => finding.confidenceLevel === 'LOW').length,
    };
    scan.findingCount = findings.length;
    scan.confidenceSummary = summary;
    const report = buildReport(scan, document, findings);
    scan.reportId = report.id;
    state.reports.unshift(report);
    state.scans.unshift(scan);
    document.scanStatus = 'COMPLETED';
    document.latestScanId = scan.id;
    document.findingCount = findings.length;
    document.riskLevel = riskFromFindings(findings);
    addAudit(state, {
      action: 'SCAN_COMPLETED',
      user: uploader,
      document,
      details: findings.length ? `${findings.length} findings detected` : 'No findings detected',
      at: startedMs + total,
    });
    if (index % 4 === 1) {
      addAudit(state, { action: 'FINDINGS_VIEWED', user: admin, document, at: startedMs + total + 3600 * 1000 });
    }
    if (index % 5 === 2) {
      addAudit(state, {
        action: 'REPORT_DOWNLOADED',
        user: PUBLIC_ACTOR,
        document,
        details: 'Exported as PDF',
        at: startedMs + total + 2 * 3600 * 1000,
      });
    }
  });

  addAudit(state, {
    action: 'LOGIN_FAILED',
    user: { id: null, name: 'Unknown account', role: 'unknown' },
    result: 'FAILURE',
    details: 'Invalid credentials',
    at: now - 0.05 * DAY,
  });
  state.auditLogs.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  return state;
}
