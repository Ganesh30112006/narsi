/**
 * Mock-only transport: an in-browser implementation of the FastAPI contract.
 * Loaded lazily and only when VITE_API_MODE=mock, so it never ships in production builds.
 */
import type { TransportRequest, TransportResponse, Transport } from '../services/transport';
import { TransportFailure } from '../services/transport';
import type { AuditLog } from '../types/audit';
import type { Permission } from '../types/auth';
import type { DocumentFileType, DocumentRecord } from '../types/document';
import type { Finding, PIIType } from '../types/finding';
import { PII_TYPES, VISUAL_TYPES } from '../types/finding';
import type { Redaction, RedactionItem } from '../types/redaction';
import type { Report, ReportExportFormat } from '../types/report';
import type { Scan, ScanStageProgress, ScanStatusSnapshot } from '../types/scan';
import { SCAN_STAGES } from '../types/scan';
import type { ScanSettings } from '../types/settings';
import { ruleForFileName, MAX_UPLOAD_BYTES } from '../utils/file';
import { AUDIT_ACTION_LABELS, PII_TYPE_LABELS } from '../utils/labels';
import { hasPermission } from '../utils/security';
import type { AuditActor, MockDocument, MockScan, MockState, MockUser } from './mockDb';
import {
  PUBLIC_ACTOR,
  SCANNER_VERSION,
  addAudit,
  buildContent,
  buildFindings,
  buildReport,
  createRng,
  createSeedState,
  hashString,
  mimeFor,
  nextId,
  riskFromFindings,
  stageDurations,
} from './mockDb';
import { PAGE_HEIGHT, PAGE_WIDTH, renderPageSvg, renderSimplePdf, renderText } from './mockPages';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Mock documents are text pages, so they only contain text values (no photos, QR codes or signatures).
const TEXT_TYPES = PII_TYPES.filter((type) => !VISUAL_TYPES.includes(type));

const SESSION_KEY = 'govpii.mock.session';
let latency = { min: 180, max: 520 };
let state: MockState = initState();

function initState(): MockState {
  const next = createSeedState();
  try {
    const stored = window.sessionStorage.getItem(SESSION_KEY);
    if (stored && next.users.some((user) => user.id === stored)) next.sessionUserId = stored;
  } catch {
    // Storage unavailable — start signed out.
  }
  return next;
}

function persistSession(userId: string | null) {
  try {
    if (userId) window.sessionStorage.setItem(SESSION_KEY, userId);
    else window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // ignore
  }
}

/** Test/dev hooks. */
export function configureMock(options: { latencyMs?: number }) {
  if (options.latencyMs !== undefined) latency = { min: options.latencyMs, max: options.latencyMs };
}

export function resetMockState() {
  persistSession(null);
  state = createSeedState();
}

export function getMockState(): MockState {
  return state;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

interface MockRequest {
  method: TransportRequest['method'];
  path: string;
  params: Record<string, string>;
  query: URLSearchParams;
  body: Record<string, unknown>;
  form: FormData | null;
  user: MockUser | null;
  request: TransportRequest;
}

interface MockResult {
  status: number;
  body?: unknown;
  headers?: Record<string, string>;
}

type Handler = (req: MockRequest) => MockResult | Promise<MockResult>;

interface Route {
  method: TransportRequest['method'];
  pattern: RegExp;
  keys: string[];
  handler: Handler;
  auth: boolean;
  permission?: Permission;
}

const routes: Route[] = [];

function route(
  method: Route['method'],
  path: string,
  handler: Handler,
  options: { auth?: boolean; permission?: Permission } = {},
) {
  const keys: string[] = [];
  const pattern = new RegExp(
    `^${path.replace(/:([a-zA-Z]+)/g, (_, key: string) => {
      keys.push(key);
      return '([^/]+)';
    })}$`,
  );
  routes.push({ method, pattern, keys, handler, auth: options.auth ?? true, permission: options.permission });
}

const ok = (body: unknown, status = 200): MockResult => ({ status, body });
const noContent = (): MockResult => ({ status: 204, body: null });
const fail = (status: number, detail: unknown): MockResult => ({ status, body: { detail } });
const notFound = (what: string) => fail(404, `${what} not found.`);
const fieldError = (field: string, msg: string) => fail(422, [{ loc: ['body', field], msg, type: 'value_error' }]);

function currentUser(): MockUser | null {
  return state.users.find((user) => user.id === state.sessionUserId) ?? null;
}

function requireUser(req: MockRequest): MockUser {
  if (!req.user) throw new Error('route requires auth');
  return req.user;
}

// ---------------------------------------------------------------------------
// Serialization — strip mock-internal fields
// ---------------------------------------------------------------------------

function publicUser(user: MockUser) {
  const { password: _password, ...rest } = user;
  return rest;
}

function publicDocument(document: MockDocument): DocumentRecord {
  const { content: _content, redactions: _redactions, ...rest } = document;
  return rest;
}

function publicScan(scan: MockScan): Scan {
  const { startedAtMs: _s, durations: _d, failAt: _f, materialized: _m, ...rest } = scan;
  return rest;
}

function publicFinding(finding: MockState['findings'][number]): Finding {
  const { rawValue: _raw, fieldKey: _key, ...rest } = finding;
  return rest;
}

function paginate<T>(items: T[], query: URLSearchParams) {
  const page = Math.max(1, Number(query.get('page') ?? 1) || 1);
  const pageSize = Math.min(100, Math.max(1, Number(query.get('pageSize') ?? 20) || 20));
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), page, pageSize, total: items.length };
}

function inDateRange(value: string, from: string | null, to: string | null) {
  const day = value.slice(0, 10);
  if (from && day < from) return false;
  if (to && day > to) return false;
  return true;
}

function compare<T>(a: T, b: T): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return a < b ? -1 : 1;
}

// ---------------------------------------------------------------------------
// Scan simulation
// ---------------------------------------------------------------------------

function advanceScan(scan: MockScan, now = Date.now()) {
  if (scan.status === 'COMPLETED' || scan.status === 'FAILED' || scan.status === 'CANCELLED') return;
  const document = state.documents.find((doc) => doc.id === scan.documentId);
  const elapsed = now - scan.startedAtMs;
  const total = scan.durations.reduce((sum, value) => sum + value, 0);
  const pages = document?.pageCount ?? 1;

  let cursor = 0;
  let failed = false;
  let activeFraction = 0;
  let activeStage: string | null = null;
  const stages: ScanStageProgress[] = SCAN_STAGES.map((stage, index) => {
    const duration = scan.durations[index] ?? 0;
    const start = cursor;
    cursor += duration;
    const startedAt = new Date(scan.startedAtMs + start).toISOString();
    if (failed) return { stage, state: 'PENDING', startedAt: null, completedAt: null };
    if (stage === 'OCR' && (duration === 0 || !scan.ocrEnabled)) {
      return { stage, state: elapsed >= start ? 'SKIPPED' : 'PENDING', startedAt: null, completedAt: null };
    }
    if (scan.failAt === stage && elapsed >= start + duration * 0.6) {
      failed = true;
      return { stage, state: 'FAILED', startedAt, completedAt: null };
    }
    if (elapsed >= cursor) {
      return { stage, state: 'COMPLETED', startedAt, completedAt: new Date(scan.startedAtMs + cursor).toISOString() };
    }
    if (elapsed >= start) {
      activeStage = stage;
      activeFraction = (elapsed - start) / duration;
      return { stage, state: 'ACTIVE', startedAt, completedAt: null };
    }
    return { stage, state: 'PENDING', startedAt: null, completedAt: null };
  });
  scan.stages = stages;

  const perPage = activeStage === 'TEXT_EXTRACTION' || activeStage === 'OCR' || activeStage === 'PII_DETECTION';
  scan.progress = {
    currentPage: perPage ? Math.min(pages, Math.max(1, Math.ceil(activeFraction * pages))) : null,
    totalPages: pages,
    percent: Math.min(99, Math.round((elapsed / total) * 100)),
  };

  const user: AuditActor | undefined =
    document?.uploadedBy.id === PUBLIC_ACTOR.id
      ? PUBLIC_ACTOR
      : (state.users.find((candidate) => candidate.id === state.sessionUserId) ?? state.users[0]);

  if (failed) {
    scan.status = 'FAILED';
    scan.error = {
      code: 'EXTRACTION_FAILED',
      message: "We couldn't read the contents of this file. It may be damaged or password-protected.",
      retryable: true,
    };
    if (document) {
      document.scanStatus = 'FAILED';
      if (user) addAudit(state, { action: 'SCAN_FAILED', user, document, result: 'FAILURE', details: 'Text extraction failed' });
    }
    return;
  }

  if (elapsed < 400) {
    scan.status = 'QUEUED';
    if (document) document.scanStatus = 'QUEUED';
    return;
  }

  if (elapsed < total) {
    scan.status = 'PROCESSING';
    if (document) document.scanStatus = 'PROCESSING';
    return;
  }

  // Completed
  scan.status = 'COMPLETED';
  scan.completedAt = new Date(scan.startedAtMs + total).toISOString();
  scan.progress = { currentPage: pages, totalPages: pages, percent: 100 };
  if (!document || scan.materialized) return;
  scan.materialized = true;

  // Findings from earlier scans of this document are superseded.
  const previousScanIds = new Set(
    state.scans.filter((other) => other.documentId === document.id && other.id !== scan.id).map((other) => other.id),
  );
  state.findings = state.findings.filter((finding) => !previousScanIds.has(finding.scanId));

  const findings = buildFindings(state, document, scan, now);
  state.findings.push(...findings);
  scan.findingCount = findings.length;
  scan.confidenceSummary = {
    high: findings.filter((finding) => finding.confidenceLevel === 'HIGH').length,
    medium: findings.filter((finding) => finding.confidenceLevel === 'MEDIUM').length,
    low: findings.filter((finding) => finding.confidenceLevel === 'LOW').length,
  };
  const report = buildReport(scan, document, findings);
  scan.reportId = report.id;
  state.reports.unshift(report);
  document.scanStatus = 'COMPLETED';
  document.findingCount = findings.length;
  document.riskLevel = riskFromFindings(findings);
  if (user) {
    addAudit(state, {
      action: 'SCAN_COMPLETED',
      user,
      document,
      details: findings.length ? `${findings.length} findings detected` : 'No findings detected',
    });
  }
}

function advanceAllScans() {
  state.scans.forEach((scan) => advanceScan(scan));
  state.redactions.forEach((redaction) => advanceRedaction(redaction));
}

// ---------------------------------------------------------------------------
// Redaction simulation
// ---------------------------------------------------------------------------

const redactionPlans = new Map<string, { completeAt: number; items: RedactionItem[]; userId: string }>();

function advanceRedaction(redaction: Redaction, now = Date.now()) {
  if (redaction.status !== 'PROCESSING') return;
  const plan = redactionPlans.get(redaction.id);
  if (!plan || now < plan.completeAt) return;
  const source = state.documents.find((doc) => doc.id === redaction.documentId);
  if (!source) {
    redaction.status = 'FAILED';
    redaction.error = 'The original document no longer exists.';
    return;
  }

  const actions: MockDocument['redactions'] = {};
  for (const item of plan.items) {
    const finding = state.findings.find((candidate) => candidate.id === item.findingId);
    if (!finding) continue;
    actions[finding.fieldKey] = item.action;
    finding.redactionState = item.action === 'REDACT' ? 'REDACTED' : item.action === 'MASK' ? 'MASKED' : 'PRESERVED';
  }

  const extensionIndex = source.fileName.lastIndexOf('.');
  const base = extensionIndex > 0 ? source.fileName.slice(0, extensionIndex) : source.fileName;
  const extension = extensionIndex > 0 ? source.fileName.slice(extensionIndex) : '';
  const user: AuditActor | undefined =
    plan.userId === PUBLIC_ACTOR.id
      ? PUBLIC_ACTOR
      : (state.users.find((candidate) => candidate.id === plan.userId) ?? state.users[0]);
  const sanitized: MockDocument = {
    ...source,
    publicToken: undefined,
    id: nextId(state, 'doc'),
    fileName: `${base}.sanitized${extension}`,
    uploadedAt: new Date(now).toISOString(),
    uploadedBy: user?.id ? { id: user.id, name: user.name } : source.uploadedBy,
    variant: 'SANITIZED',
    sourceDocumentId: source.id,
    scanStatus: 'NOT_SCANNED',
    latestScanId: null,
    findingCount: null,
    riskLevel: null,
    redactions: actions,
  };
  state.documents.unshift(sanitized);

  const scanFindings = state.findings.filter((finding) => finding.scanId === source.latestScanId);
  const report = state.reports.find((candidate) => candidate.scanId === source.latestScanId);
  if (report) {
    const removed = scanFindings.filter(
      (finding) => finding.redactionState === 'REDACTED' || finding.redactionState === 'MASKED',
    ).length;
    report.redactionStatus = removed === 0 ? 'NOT_REDACTED' : removed === scanFindings.length ? 'REDACTED' : 'PARTIALLY_REDACTED';
  }

  redaction.status = 'COMPLETED';
  redaction.completedAt = new Date(now).toISOString();
  redaction.sanitizedDocumentId = sanitized.id;
  redaction.sanitizedFileName = sanitized.fileName;
  if (user) {
    addAudit(state, {
      action: 'REDACTION_CREATED',
      user,
      document: source,
      details: `${redaction.counts.redacted} redacted, ${redaction.counts.masked} masked, ${redaction.counts.preserved} preserved`,
    });
  }
}

// ---------------------------------------------------------------------------
// Routes: auth
// ---------------------------------------------------------------------------

route(
  'GET',
  '/health',
  () => ok({ status: 'healthy', checkedAt: new Date().toISOString(), version: SCANNER_VERSION, checks: [] }),
  {
    auth: false,
  },
);

route(
  'POST',
  '/auth/login',
  (req) => {
    if (state.failedLogins >= 5) return fail(429, 'Too many sign-in attempts. Please wait a few minutes.');
    const username = String(req.body.username ?? '')
      .trim()
      .toLowerCase();
    const password = String(req.body.password ?? '');
    const user = state.users.find((candidate) => candidate.username === username && candidate.password === password);
    if (!user) {
      state.failedLogins += 1;
      return fail(401, 'Incorrect username or password.');
    }
    state.failedLogins = 0;
    state.sessionUserId = user.id;
    user.lastLoginAt = new Date().toISOString();
    persistSession(user.id);
    addAudit(state, { action: 'LOGIN', user });
    return ok(publicUser(user));
  },
  { auth: false },
);

route(
  'POST',
  '/auth/logout',
  (req) => {
    if (req.user) addAudit(state, { action: 'LOGOUT', user: req.user });
    state.sessionUserId = null;
    persistSession(null);
    return noContent();
  },
  { auth: false },
);

route('GET', '/auth/me', (req) => ok(publicUser(requireUser(req))));

route('POST', '/auth/change-password', (req) => {
  const user = requireUser(req);
  const current = String(req.body.currentPassword ?? '');
  const next = String(req.body.newPassword ?? '');
  if (current !== user.password) return fieldError('currentPassword', 'Current password is incorrect.');
  if (next.length < 12) return fieldError('newPassword', 'Password must be at least 12 characters.');
  if (next === current) return fieldError('newPassword', 'Choose a password you have not used before.');
  user.password = next;
  addAudit(state, { action: 'PASSWORD_CHANGED', user });
  return noContent();
});

route('PATCH', '/users/me', (req) => {
  const user = requireUser(req);
  const name = String(req.body.name ?? '').trim();
  if (!name) return fieldError('name', 'Name is required.');
  if (name.length > 80) return fieldError('name', 'Name must be 80 characters or fewer.');
  user.name = name;
  return ok(publicUser(user));
});

route('GET', '/auth/sessions', () => ok(state.sessions));

route('POST', '/auth/sessions/revoke-all', (req) => {
  addAudit(state, { action: 'LOGOUT', user: requireUser(req), details: 'Signed out of all sessions' });
  state.sessionUserId = null;
  state.sessions = state.sessions.filter((session) => session.current);
  persistSession(null);
  return noContent();
});

route('GET', '/api-keys', (req) => {
  const user = requireUser(req);
  return ok(state.apiKeys.filter((key) => key.userId === user.id).map(({ userId: _userId, ...key }) => key));
});

route('POST', '/api-keys', (req) => {
  const user = requireUser(req);
  const name = String(req.body.name ?? '').trim();
  if (!name) return fieldError('name', 'Give the key a name');
  const key = `gpk_mock${String(++state.seq).padStart(4, '0')}${'x'.repeat(32)}`;
  const row = { id: `key_${state.seq}`, name, prefix: key.slice(0, 10), createdAt: new Date().toISOString(), lastUsedAt: null };
  state.apiKeys.push({ ...row, userId: user.id });
  addAudit(state, { action: 'USER_UPDATED', user, details: `API key created: ${name}` });
  return ok({ ...row, key }, 201);
});

route('DELETE', '/api-keys/:id', (req) => {
  const user = requireUser(req);
  const index = state.apiKeys.findIndex((key) => key.id === req.params.id && key.userId === user.id);
  if (index === -1) return notFound('API key');
  const [removed] = state.apiKeys.splice(index, 1);
  addAudit(state, { action: 'USER_UPDATED', user, details: `API key revoked: ${removed?.name ?? ''}` });
  return noContent();
});

// ---------------------------------------------------------------------------
// Routes: dashboard & settings
// ---------------------------------------------------------------------------

route('GET', '/dashboard/summary', (req) => {
  advanceAllScans();
  const user = requireUser(req);
  const originals = state.documents.filter((doc) => doc.variant === 'ORIGINAL');
  const scanned = originals.filter((doc) => doc.scanStatus === 'COMPLETED');
  const counts = new Map<PIIType, number>();
  state.findings.forEach((finding) => counts.set(finding.piiType, (counts.get(finding.piiType) ?? 0) + 1));
  const activity: AuditLog[] = hasPermission(user.role, 'audit:read')
    ? state.auditLogs
    : state.auditLogs.filter((log) => log.user.id === user.id);
  return ok({
    stats: {
      documentsScanned: scanned.length,
      documentsWithPii: scanned.filter((doc) => (doc.findingCount ?? 0) > 0).length,
      totalFindings: state.findings.length,
      highConfidenceFindings: state.findings.filter((finding) => finding.confidenceLevel === 'HIGH').length,
    },
    piiDistribution: PII_TYPES.map((piiType) => ({ piiType, count: counts.get(piiType) ?? 0 })).sort((a, b) => b.count - a.count),
    recentScans: [...state.scans]
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .slice(0, 6)
      .map((scan) => {
        const document = state.documents.find((doc) => doc.id === scan.documentId);
        return {
          id: scan.id,
          documentId: scan.documentId,
          documentName: scan.documentName,
          status: scan.status,
          findingCount: scan.findingCount,
          riskLevel: scan.status === 'COMPLETED' ? (document?.riskLevel ?? null) : null,
          createdAt: scan.createdAt,
          completedAt: scan.completedAt,
        };
      }),
    recentActivity: activity.slice(0, 6),
  });
});

route('GET', '/settings', () => ok(state.settings));

route(
  'PUT',
  '/settings',
  (req) => {
    const body = req.body as Partial<ScanSettings>;
    const threshold = Number(body.confidenceThreshold);
    const retention = Number(body.retentionDays);
    if (!(threshold >= 0 && threshold <= 1)) return fieldError('confidenceThreshold', 'Threshold must be between 0 and 100%.');
    if (!(retention >= 7 && retention <= 3650)) return fieldError('retentionDays', 'Retention must be between 7 and 3650 days.');
    state.settings = {
      ocrEnabled: Boolean(body.ocrEnabled),
      confidenceThreshold: threshold,
      defaultRedactionMode: body.defaultRedactionMode === 'MASK' ? 'MASK' : 'REDACT',
      retentionDays: retention,
      autoDeleteEnabled: Boolean(body.autoDeleteEnabled),
    };
    addAudit(state, { action: 'SETTINGS_UPDATED', user: requireUser(req), details: 'Scan and retention settings updated' });
    return ok(state.settings);
  },
  { permission: 'settings:manage' },
);

// ---------------------------------------------------------------------------
// Routes: documents
// ---------------------------------------------------------------------------

function findDocument(id: string | undefined) {
  return state.documents.find((doc) => doc.id === id);
}

route('GET', '/documents', (req) => {
  advanceAllScans();
  const q = req.query;
  const search = (q.get('search') ?? '').trim().toLowerCase();
  const sortBy = (q.get('sortBy') ?? 'uploadedAt') as keyof DocumentRecord;
  const order = q.get('sortOrder') === 'asc' ? 1 : -1;
  const items = state.documents
    .filter((doc) => !search || doc.fileName.toLowerCase().includes(search))
    .filter((doc) => !q.get('fileType') || doc.fileType === q.get('fileType'))
    .filter((doc) => !q.get('scanStatus') || doc.scanStatus === q.get('scanStatus'))
    .filter((doc) => !q.get('variant') || doc.variant === q.get('variant'))
    .filter((doc) => inDateRange(doc.uploadedAt, q.get('uploadedFrom'), q.get('uploadedTo')))
    .sort((a, b) => compare(a[sortBy], b[sortBy]) * order)
    .map(publicDocument);
  return ok(paginate(items, q));
});

route(
  'POST',
  '/documents',
  (req) => {
    const created = createDocument(req.form?.get('file'), requireUser(req));
    return 'error' in created ? created.error : ok(publicDocument(created.document), 201);
  },
  { permission: 'documents:upload' },
);

/** Validates an uploaded file and stores it as a new document (shared by admin and public uploads). */
function createDocument(
  file: FormDataEntryValue | null | undefined,
  owner: AuditActor & { id: string },
  publicToken?: string,
): { document: MockDocument } | { error: MockResult } {
  if (!(file instanceof File)) return { error: fieldError('file', 'A file is required.') };
  const rule = ruleForFileName(file.name);
  if (!rule) return { error: fail(415, "This file type isn't supported.") };
  if (file.size === 0) return { error: fieldError('file', 'This file is empty.') };
  if (file.size > MAX_UPLOAD_BYTES) return { error: fail(413, 'This file exceeds the maximum upload size.') };

  const seed = hashString(`${file.name}:${file.size}:${Date.now()}`);
  const rng = createRng(seed);
  const clean = /clean|public|notice|blurry|unreadable/i.test(file.name);
  const pageCount = rule.type === 'PNG' || rule.type === 'JPG' ? 1 : rng.int(1, 5);
  const plan: PIIType[][] = Array.from({ length: pageCount }, () =>
    clean ? [] : Array.from({ length: rng.int(0, 4) }, () => rng.pick(TEXT_TYPES)),
  );
  const document: MockDocument = {
    id: nextId(state, 'doc'),
    fileName: file.name,
    fileType: rule.type as DocumentFileType,
    mimeType: file.type || mimeFor(rule.type),
    sizeBytes: file.size,
    pageCount,
    uploadedAt: new Date().toISOString(),
    uploadedBy: { id: owner.id, name: owner.name },
    variant: 'ORIGINAL',
    sourceDocumentId: null,
    scanStatus: 'NOT_SCANNED',
    latestScanId: null,
    findingCount: null,
    riskLevel: null,
    content: buildContent(file.name, plan),
    redactions: {},
    publicToken,
  };
  state.documents.unshift(document);
  addAudit(state, { action: 'DOCUMENT_UPLOADED', user: owner, document });
  return { document };
}

route('GET', '/documents/:id', (req) => {
  advanceAllScans();
  const document = findDocument(req.params.id);
  return document ? ok(publicDocument(document)) : notFound('Document');
});

route(
  'DELETE',
  '/documents/:id',
  (req) => {
    const document = findDocument(req.params.id);
    if (!document) return notFound('Document');
    purgeDocument(document, requireUser(req));
    return noContent();
  },
  { permission: 'documents:delete' },
);

function purgeDocument(document: MockDocument, actor: AuditActor, details?: string) {
  const scanIds = new Set(state.scans.filter((scan) => scan.documentId === document.id).map((scan) => scan.id));
  state.documents = state.documents.filter((doc) => doc.id !== document.id);
  state.findings = state.findings.filter((finding) => finding.documentId !== document.id);
  state.reports = state.reports.filter((report) => !scanIds.has(report.scanId));
  state.scans = state.scans.filter((scan) => scan.documentId !== document.id);
  addAudit(state, { action: 'DOCUMENT_DELETED', user: actor, document, details: details ?? null });
}

route(
  'GET',
  '/documents/:id/download',
  (req) => {
    const document = findDocument(req.params.id);
    return document ? downloadDocument(document, requireUser(req)) : notFound('Document');
  },
  { permission: 'documents:download' },
);

function downloadDocument(document: MockDocument, actor: AuditActor): MockResult {
  addAudit(state, {
    action: 'DOCUMENT_DOWNLOADED',
    user: actor,
    document,
    details: document.variant === 'SANITIZED' ? 'Sanitized copy' : 'Original document',
  });
  const text = renderText(document.content, document.redactions);
  return {
    status: 200,
    body: new Blob([text], { type: 'text/plain' }),
    headers: { 'content-disposition': `attachment; filename="${document.fileName}.mock.txt"` },
  };
}

route('GET', '/documents/:id/pages', (req) => {
  const document = findDocument(req.params.id);
  if (!document) return notFound('Document');
  return ok(document.content.map((_, index) => ({ pageNumber: index + 1, width: PAGE_WIDTH, height: PAGE_HEIGHT })));
});

route('GET', '/documents/:id/pages/:page/image', (req) => {
  const document = findDocument(req.params.id);
  const pageNumber = Number(req.params.page);
  const page = document?.content[pageNumber - 1];
  if (!document || !page) return notFound('Page');
  const svg = renderPageSvg(page, pageNumber, document.content.length, document.redactions);
  return { status: 200, body: new Blob([svg], { type: 'image/svg+xml' }) };
});

// ---------------------------------------------------------------------------
// Routes: scans
// ---------------------------------------------------------------------------

route(
  'POST',
  '/scans',
  (req) => {
    const document = findDocument(String(req.body.documentId ?? ''));
    if (!document) return notFound('Document');
    advanceAllScans();
    const running = state.scans.find(
      (scan) => scan.documentId === document.id && (scan.status === 'QUEUED' || scan.status === 'PROCESSING'),
    );
    if (running) return fail(409, 'A scan is already running for this document.');
    const ocrEnabled = typeof req.body.ocrEnabled === 'boolean' ? req.body.ocrEnabled : undefined;
    return ok(publicScan(startScan(document, requireUser(req), ocrEnabled)), 201);
  },
  { permission: 'scans:create' },
);

function startScan(document: MockDocument, actor: AuditActor, requestedOcr?: boolean): MockScan {
  const ocrEnabled = requestedOcr ?? state.settings.ocrEnabled;
  const needsOcr = ocrEnabled && ['PNG', 'JPG', 'TIFF', 'PDF'].includes(document.fileType);
  const pageCount = document.pageCount ?? 1;
  const now = Date.now();
  const scan: MockScan = {
    id: nextId(state, 'scn'),
    documentId: document.id,
    documentName: document.fileName,
    status: 'QUEUED',
    stages: SCAN_STAGES.map((stage) => ({ stage, state: 'PENDING', startedAt: null, completedAt: null })),
    progress: { currentPage: null, totalPages: pageCount, percent: 0 },
    ocrEnabled: needsOcr,
    scannerVersion: SCANNER_VERSION,
    createdAt: new Date(now).toISOString(),
    startedAt: new Date(now).toISOString(),
    completedAt: null,
    findingCount: null,
    confidenceSummary: null,
    reportId: null,
    error: null,
    startedAtMs: now,
    durations: stageDurations(pageCount, needsOcr),
    failAt: /corrupt|damaged/i.test(document.fileName) ? 'TEXT_EXTRACTION' : null,
    materialized: false,
  };
  // A photo too blurred or dark to read: the backend reports the page, and the results must not call it clean.
  if (needsOcr && /blurry|unreadable/i.test(document.fileName)) {
    scan.unreadablePages = [1];
    scan.warnings = ['Page 1: text recognition quality is low; findings may be missed.'];
  }
  state.scans.unshift(scan);
  document.scanStatus = 'QUEUED';
  document.latestScanId = scan.id;
  addAudit(state, { action: 'SCAN_STARTED', user: actor, document });
  return scan;
}

route('GET', '/scans/:id', (req) => {
  const scan = state.scans.find((candidate) => candidate.id === req.params.id);
  if (!scan) return notFound('Scan');
  advanceScan(scan);
  return ok(publicScan(scan));
});

route(
  'POST',
  '/scans/:id/retry',
  (req) => {
    const scan = state.scans.find((candidate) => candidate.id === req.params.id);
    if (!scan) return notFound('Scan');
    if (scan.status !== 'FAILED') return fail(409, 'Only failed scans can be retried.');
    const document = findDocument(scan.documentId);
    scan.status = 'QUEUED';
    scan.error = null;
    scan.startedAtMs = Date.now();
    scan.startedAt = new Date().toISOString();
    scan.stages = SCAN_STAGES.map((stage) => ({ stage, state: 'PENDING', startedAt: null, completedAt: null }));
    scan.materialized = false;
    if (document) document.scanStatus = 'QUEUED';
    addAudit(state, { action: 'SCAN_STARTED', user: requireUser(req), document: document ?? null, details: 'Retry' });
    return ok(publicScan(scan));
  },
  { permission: 'scans:create' },
);

route('GET', '/scans/:id/status', (req) => {
  const scan = state.scans.find((candidate) => candidate.id === req.params.id);
  if (!scan) return notFound('Scan');
  advanceScan(scan);
  const snapshot: ScanStatusSnapshot = {
    id: scan.id,
    status: scan.status,
    stages: scan.stages,
    progress: scan.progress,
    error: scan.error,
    findingCount: scan.findingCount,
  };
  return ok(snapshot);
});

// ---------------------------------------------------------------------------
// Routes: findings
// ---------------------------------------------------------------------------

const viewedScans = new Set<string>();

route('GET', '/findings', (req) => {
  advanceAllScans();
  const q = req.query;
  const search = (q.get('search') ?? '').trim().toLowerCase();
  const sortBy = q.get('sortBy') ?? 'confidence';
  const order = q.get('sortOrder') === 'asc' ? 1 : -1;
  const scanId = q.get('scanId');
  const method = q.get('detectionMethod');
  const items = state.findings
    .filter(
      (finding) =>
        !search ||
        finding.documentName.toLowerCase().includes(search) ||
        PII_TYPE_LABELS[finding.piiType].toLowerCase().includes(search),
    )
    .filter((finding) => !q.get('piiType') || finding.piiType === q.get('piiType'))
    .filter((finding) => !q.get('confidenceLevel') || finding.confidenceLevel === q.get('confidenceLevel'))
    .filter(
      (finding) =>
        !method || finding.detectionMethod === method || finding.detectionSignals.includes(method as Finding['detectionMethod']),
    )
    .filter((finding) => !q.get('documentId') || finding.documentId === q.get('documentId'))
    .filter((finding) => !scanId || finding.scanId === scanId)
    .filter((finding) => inDateRange(finding.createdAt, q.get('createdFrom'), q.get('createdTo')))
    .sort((a, b) => {
      const key = (finding: Finding) =>
        sortBy === 'page'
          ? (finding.location.page ?? 0)
          : sortBy === 'createdAt'
            ? finding.createdAt
            : sortBy === 'piiType'
              ? finding.piiType
              : finding.confidence;
      return compare(key(a), key(b)) * order || compare(a.location.page ?? 0, b.location.page ?? 0);
    })
    .map(publicFinding);

  if (scanId && req.user && !viewedScans.has(scanId)) {
    viewedScans.add(scanId);
    const scan = state.scans.find((candidate) => candidate.id === scanId);
    addAudit(state, {
      action: 'FINDINGS_VIEWED',
      user: req.user,
      document: scan ? (findDocument(scan.documentId) ?? null) : null,
    });
  }
  return ok(paginate(items, q));
});

route('GET', '/findings/:id', (req) => {
  const finding = state.findings.find((candidate) => candidate.id === req.params.id);
  return finding ? ok(publicFinding(finding)) : notFound('Finding');
});

route('POST', '/findings/:id/reveal', (req) => {
  const user = requireUser(req);
  const finding = state.findings.find((candidate) => candidate.id === req.params.id);
  if (!finding) return notFound('Finding');
  const document = findDocument(finding.documentId) ?? null;
  if (!hasPermission(user.role, 'pii:reveal')) {
    addAudit(state, {
      action: 'PII_REVEALED',
      user,
      document,
      result: 'DENIED',
      details: `${PII_TYPE_LABELS[finding.piiType]} reveal denied — insufficient role`,
    });
    return fail(403, "Your role doesn't allow revealing masked values.");
  }
  const reason = String(req.body.reason ?? '').trim();
  if (reason.length < 5) return fieldError('reason', 'Describe why you need to see this value.');
  addAudit(state, {
    action: 'PII_REVEALED',
    user,
    document,
    details: `${PII_TYPE_LABELS[finding.piiType]} on page ${finding.location.page ?? '—'} · Reason: ${reason.slice(0, 80)}`,
  });
  return ok({ findingId: finding.id, value: finding.rawValue, expiresAt: new Date(Date.now() + 30_000).toISOString() });
});

// ---------------------------------------------------------------------------
// Routes: redactions
// ---------------------------------------------------------------------------

route(
  'POST',
  '/redactions',
  (req) => {
    const user = requireUser(req);
    const document = findDocument(String(req.body.documentId ?? ''));
    if (!document) return notFound('Document');
    const items = Array.isArray(req.body.items) ? (req.body.items as RedactionItem[]) : [];
    if (items.length === 0) return fieldError('items', 'Select at least one finding.');
    const valid = items.every((item) =>
      state.findings.some((finding) => finding.id === item.findingId && finding.documentId === document.id),
    );
    if (!valid) return fieldError('items', 'Some selected findings do not belong to this document.');
    return ok(queueRedaction(document, items, user.id), 202);
  },
  { permission: 'redactions:create' },
);

function queueRedaction(document: MockDocument, items: RedactionItem[], userId: string): Redaction {
  const redaction: Redaction = {
    id: nextId(state, 'red'),
    documentId: document.id,
    sourceFileName: document.fileName,
    status: 'PROCESSING',
    sanitizedDocumentId: null,
    sanitizedFileName: null,
    counts: {
      redacted: items.filter((item) => item.action === 'REDACT').length,
      masked: items.filter((item) => item.action === 'MASK').length,
      preserved: items.filter((item) => item.action === 'PRESERVE').length,
    },
    createdAt: new Date().toISOString(),
    completedAt: null,
    error: null,
  };
  redactionPlans.set(redaction.id, { completeAt: Date.now() + Math.max(latency.max * 3, 0), items, userId });
  state.redactions.unshift(redaction);
  advanceRedaction(redaction);
  return redaction;
}

route('GET', '/redactions/:id', (req) => {
  const redaction = state.redactions.find((candidate) => candidate.id === req.params.id);
  if (!redaction) return notFound('Redaction');
  advanceRedaction(redaction);
  return ok(redaction);
});

// ---------------------------------------------------------------------------
// Routes: reports
// ---------------------------------------------------------------------------

route('GET', '/reports', (req) => {
  advanceAllScans();
  const search = (req.query.get('search') ?? '').trim().toLowerCase();
  const items = state.reports
    .filter((report) => !search || report.documentName.toLowerCase().includes(search))
    .sort((a, b) => b.generatedAt.localeCompare(a.generatedAt))
    .map(({ id, scanId, documentId, documentName, generatedAt, totalFindings, highConfidenceFindings, redactionStatus }) => ({
      id,
      scanId,
      documentId,
      documentName,
      generatedAt,
      totalFindings,
      highConfidenceFindings,
      redactionStatus,
    }));
  return ok(paginate(items, req.query));
});

route('GET', '/reports/:id', (req) => {
  const report = state.reports.find((candidate) => candidate.id === req.params.id);
  return report ? ok(report) : notFound('Report');
});

route(
  'GET',
  '/reports/:id/download',
  (req) => {
    const report = state.reports.find((candidate) => candidate.id === req.params.id);
    if (!report) return notFound('Report');
    return exportReport(report, (req.query.get('format') ?? 'json') as ReportExportFormat, requireUser(req));
  },
  { permission: 'reports:export' },
);

function exportReport(report: Report, format: ReportExportFormat, actor: AuditActor): MockResult {
  const base = `govpii-report-${report.documentName.replace(/\.[^.]+$/, '')}`;
  let blob: Blob;
  if (format === 'json') {
    blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
  } else if (format === 'csv') {
    const rows = [
      'section,key,count',
      ...report.categories.map((row) => `category,${row.piiType},${row.count}`),
      ...report.confidenceDistribution.map((row) => `confidence,${row.level},${row.count}`),
      ...report.pageDistribution.map((row) => `page,${row.page},${row.count}`),
      ...report.detectionMethods.map((row) => `method,${row.method},${row.count}`),
    ];
    blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  } else if (format === 'pdf') {
    blob = renderSimplePdf(`GovPII Guard scan report`, [
      `Document: ${report.documentName}`,
      `Generated: ${report.generatedAt}`,
      `Scanner: ${report.scannerVersion}`,
      `Total findings: ${report.totalFindings}`,
      '',
      'Categories:',
      ...report.categories.map((row) => `  ${PII_TYPE_LABELS[row.piiType]}: ${row.count}`),
      '',
      'Confidence:',
      ...report.confidenceDistribution.map((row) => `  ${row.level}: ${row.count}`),
      '',
      'Values are not included in this report.',
    ]);
  } else {
    return fail(422, 'Unsupported export format.');
  }
  const document = findDocument(report.documentId) ?? null;
  addAudit(state, {
    action: 'REPORT_DOWNLOADED',
    user: actor,
    document,
    details: `Exported as ${format.toUpperCase()}`,
  });
  return { status: 200, body: blob, headers: { 'content-disposition': `attachment; filename="${base}.${format}"` } };
}

// ---------------------------------------------------------------------------
// Routes: public (no sign-in) — mirrors /public/* on the backend
// ---------------------------------------------------------------------------

const PUBLIC_RETENTION_MS = 24 * 3600 * 1000;

function newAccessToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Mirrors the backend: one opaque key per distinct value, different for every upload. */
function valueGroup(scanId: string, finding: MockState['findings'][number]): string {
  let hash = 0x811c9dc5;
  for (const char of `${scanId}:${finding.piiType}:${finding.rawValue}`) {
    hash = Math.imul(hash ^ char.charCodeAt(0), 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

function publicExpiry(document: MockDocument): string {
  return new Date(Date.parse(document.uploadedAt) + PUBLIC_RETENTION_MS).toISOString();
}

/** The scan and document an access token opens. A wrong or missing token looks exactly like a missing scan. */
function resolvePublic(req: MockRequest): { scan: MockScan; document: MockDocument } | null {
  const token = req.request.headers['X-Access-Token'];
  const scan = state.scans.find((candidate) => candidate.id === req.params.id);
  const document = scan ? findDocument(scan.documentId) : undefined;
  if (!token || !scan || !document?.publicToken || document.publicToken !== token) return null;
  advanceScan(scan);
  return { scan, document };
}

function latestRedaction(document: MockDocument): Redaction | null {
  const redaction = state.redactions.find((candidate) => candidate.documentId === document.id) ?? null;
  if (redaction) advanceRedaction(redaction);
  return redaction;
}

const PUBLIC = { auth: false } as const;

route(
  'POST',
  '/public/uploads',
  (req) => {
    const token = newAccessToken();
    const created = createDocument(req.form?.get('file'), PUBLIC_ACTOR, token);
    if ('error' in created) return created.error;
    const scan = startScan(created.document, PUBLIC_ACTOR);
    return ok(
      {
        scanId: scan.id,
        accessToken: token,
        documentName: created.document.fileName,
        expiresAt: publicExpiry(created.document),
      },
      201,
    );
  },
  PUBLIC,
);

route(
  'GET',
  '/public/scans/:id/status',
  (req) => {
    const found = resolvePublic(req);
    if (!found) return notFound('Scan');
    const { id, status, stages, progress, error, findingCount } = found.scan;
    const snapshot: ScanStatusSnapshot = { id, status, stages, progress, error, findingCount };
    return ok(snapshot);
  },
  PUBLIC,
);

route(
  'GET',
  '/public/scans/:id',
  (req) => {
    const found = resolvePublic(req);
    if (!found) return notFound('Scan');
    const { scan, document } = found;
    const findings =
      scan.status === 'COMPLETED'
        ? state.findings
            .filter((finding) => finding.scanId === scan.id)
            .sort((a, b) => b.confidence - a.confidence)
            .map((finding) => ({ ...publicFinding(finding), group: valueGroup(scan.id, finding) }))
        : [];
    return ok({
      scan: publicScan(scan),
      findings,
      redaction: latestRedaction(document),
      signatures: [],
      reportAvailable: state.reports.some((report) => report.scanId === scan.id),
      expiresAt: publicExpiry(document),
    });
  },
  PUBLIC,
);

route(
  'POST',
  '/public/scans/:id/redaction',
  (req) => {
    const found = resolvePublic(req);
    if (!found) return notFound('Scan');
    const { scan, document } = found;
    if (scan.status !== 'COMPLETED') return fail(409, 'Redaction needs a completed scan.');
    const findings = state.findings.filter((finding) => finding.scanId === scan.id);
    if (findings.length === 0) return fail(409, 'Nothing was found in this file, so there is nothing to redact.');
    if (latestRedaction(document)?.status === 'PROCESSING') return fail(409, 'A redaction is already in progress.');
    const action = req.body.action === 'MASK' ? 'MASK' : 'REDACT';
    const items = findings.map((finding) => ({ findingId: finding.id, action }) as const);
    return ok(queueRedaction(document, items, PUBLIC_ACTOR.id), 202);
  },
  PUBLIC,
);

route(
  'GET',
  '/public/scans/:id/redaction/download',
  (req) => {
    const found = resolvePublic(req);
    if (!found) return notFound('Scan');
    const redaction = latestRedaction(found.document);
    const copy =
      redaction?.status === 'COMPLETED' && redaction.sanitizedDocumentId
        ? findDocument(redaction.sanitizedDocumentId)
        : undefined;
    return copy ? downloadDocument(copy, PUBLIC_ACTOR) : fail(409, "The redacted copy isn't ready.");
  },
  PUBLIC,
);

route(
  'GET',
  '/public/scans/:id/report',
  (req) => {
    const found = resolvePublic(req);
    if (!found) return notFound('Scan');
    const report = state.reports.find((candidate) => candidate.scanId === found.scan.id);
    if (!report) return fail(409, "The report isn't ready yet.");
    return exportReport(report, (req.query.get('format') ?? 'pdf') as ReportExportFormat, PUBLIC_ACTOR);
  },
  PUBLIC,
);

route(
  'DELETE',
  '/public/scans/:id',
  (req) => {
    const found = resolvePublic(req);
    if (!found) return notFound('Scan');
    const { scan, document } = found;
    if (scan.status === 'QUEUED' || scan.status === 'PROCESSING') {
      return fail(409, 'Your file is still being processed. Try again in a moment.');
    }
    state.documents
      .filter((candidate) => candidate.sourceDocumentId === document.id)
      .forEach((copy) => purgeDocument(copy, PUBLIC_ACTOR, 'Deleted by the uploader'));
    purgeDocument(document, PUBLIC_ACTOR, 'Deleted by the uploader');
    return noContent();
  },
  PUBLIC,
);

// ---------------------------------------------------------------------------
// Routes: audit
// ---------------------------------------------------------------------------

route(
  'GET',
  '/audit-logs',
  (req) => {
    const q = req.query;
    const search = (q.get('search') ?? '').trim().toLowerCase();
    const items = state.auditLogs
      .filter(
        (log) =>
          !search ||
          log.user.name.toLowerCase().includes(search) ||
          (log.documentName ?? '').toLowerCase().includes(search) ||
          AUDIT_ACTION_LABELS[log.action].toLowerCase().includes(search),
      )
      .filter((log) => !q.get('action') || log.action === q.get('action'))
      .filter((log) => !q.get('result') || log.result === q.get('result'))
      .filter((log) => !q.get('userId') || log.user.id === q.get('userId'))
      .filter((log) => inDateRange(log.timestamp, q.get('from'), q.get('to')));
    return ok(paginate(items, q));
  },
  { permission: 'audit:read' },
);

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new TransportFailure('aborted'));
      return;
    }
    if (ms <= 0) {
      resolve();
      return;
    }
    const timer = window.setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer);
        reject(new TransportFailure('aborted'));
      },
      { once: true },
    );
  });
}

async function simulateUpload(request: TransportRequest) {
  if (!(request.body instanceof FormData) || !request.onUploadProgress) return;
  const file = request.body.get('file');
  const size = file instanceof File ? file.size : 1;
  const steps = 8;
  const duration = latency.max === 0 ? 0 : Math.min(2600, 500 + size / 4000);
  for (let step = 1; step <= steps; step += 1) {
    await delay(duration / steps, request.signal);
    request.onUploadProgress((size * step) / steps, size);
  }
}

async function handle(request: TransportRequest): Promise<TransportResponse> {
  await delay(latency.min + Math.random() * (latency.max - latency.min), request.signal);
  await simulateUpload(request);

  const match = routes
    .filter((candidate) => candidate.method === request.method)
    .map((candidate) => ({ candidate, result: candidate.pattern.exec(request.path) }))
    .find((entry) => entry.result);

  if (!match?.result) {
    return { status: 404, headers: {}, body: { detail: 'Not found.' } };
  }

  const params: Record<string, string> = {};
  match.candidate.keys.forEach((key, index) => {
    params[key] = decodeURIComponent(match.result?.[index + 1] ?? '');
  });

  const user = currentUser();
  if (match.candidate.auth && !user) {
    return { status: 401, headers: {}, body: { detail: 'Not authenticated.' } };
  }
  if (match.candidate.permission && !hasPermission(user?.role, match.candidate.permission)) {
    return { status: 403, headers: {}, body: { detail: "You don't have permission to do this." } };
  }

  let body: Record<string, unknown> = {};
  if (typeof request.body === 'string') {
    try {
      body = JSON.parse(request.body) as Record<string, unknown>;
    } catch {
      return { status: 400, headers: {}, body: { detail: 'Malformed JSON.' } };
    }
  }

  const result = await match.candidate.handler({
    method: request.method,
    path: request.path,
    params,
    query: request.query,
    body,
    form: request.body instanceof FormData ? request.body : null,
    user,
    request,
  });

  const response: TransportResponse = {
    status: result.status,
    headers: { 'x-request-id': `mock-${Math.random().toString(36).slice(2, 10)}`, ...(result.headers ?? {}) },
    body: result.body ?? null,
  };
  return response;
}

// ---------------------------------------------------------------------------
// Envelope adapter — mirrors the real backend's `{ data, meta, error }` contract
// ---------------------------------------------------------------------------

const ERROR_CODES: Record<number, string> = {
  400: 'VALIDATION_ERROR',
  401: 'UNAUTHORIZED',
  403: 'FORBIDDEN',
  404: 'NOT_FOUND',
  409: 'CONFLICT',
  413: 'DOCUMENT_TOO_LARGE',
  415: 'UNSUPPORTED_FILE_TYPE',
  422: 'VALIDATION_ERROR',
  429: 'RATE_LIMITED',
  500: 'SERVER_ERROR',
};

function isPage(body: unknown): body is { items: unknown[]; page: number; pageSize: number; total: number } {
  return typeof body === 'object' && body !== null && Array.isArray((body as { items?: unknown }).items) && 'total' in body;
}

function toEnvelope(response: TransportResponse): TransportResponse {
  const { status, body } = response;
  if (body instanceof Blob || status === 204) return response;
  if (status >= 400) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const details = Array.isArray(detail)
      ? detail.map((item: { loc?: unknown[]; msg?: string }) => ({
          field: String(item.loc?.[item.loc.length - 1] ?? '_'),
          message: item.msg ?? 'Invalid value',
        }))
      : [];
    const message = typeof detail === 'string' ? detail : "Some of the information provided isn't valid.";
    const code =
      status === 401 && message.startsWith('Incorrect') ? 'INVALID_CREDENTIALS' : (ERROR_CODES[status] ?? 'SERVER_ERROR');
    return {
      ...response,
      body: { data: null, meta: {}, error: { code, message, details, requestId: response.headers['x-request-id'] } },
    };
  }
  if (isPage(body)) {
    const { items, page, pageSize, total } = body;
    const meta = { page, pageSize, total, totalPages: Math.max(1, Math.ceil(total / pageSize)) };
    return { ...response, body: { data: items, meta, error: null } };
  }
  return { ...response, body: { data: body, meta: {}, error: null } };
}

export const mockTransport: Transport = async (request) => toEnvelope(await handle(request));
