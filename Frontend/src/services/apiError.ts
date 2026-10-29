import type { ApiErrorKind, FieldErrors } from '../types/api';

const DEFAULT_MESSAGES: Record<ApiErrorKind, string> = {
  unauthorized: 'Your session has expired. Please sign in again.',
  forbidden: "You don't have permission to do this.",
  validation: "Some of the information provided isn't valid.",
  not_found: "We couldn't find what you were looking for.",
  conflict: 'This action conflicts with the current state. Refresh and try again.',
  payload_too_large: 'This file is larger than the server allows.',
  rate_limited: 'Too many requests. Please wait a moment and try again.',
  server: "The server couldn't complete this request. Please try again.",
  network: "We couldn't reach the server. Check your connection and try again.",
  timeout: 'The request took too long. Please try again.',
  cancelled: 'The request was cancelled.',
  unknown: 'Something went wrong. Please try again.',
};

/** Stable machine-readable codes returned by the backend in `error.code`. */
export type ApiErrorCode =
  | 'VALIDATION_ERROR'
  | 'INVALID_CREDENTIALS'
  | 'UNAUTHORIZED'
  | 'TOKEN_EXPIRED'
  | 'FORBIDDEN'
  | 'CSRF_FAILED'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'DUPLICATE_DOCUMENT'
  | 'DOCUMENT_TOO_LARGE'
  | 'UNSUPPORTED_FILE_TYPE'
  | 'INVALID_FILE'
  | 'SCAN_IN_PROGRESS'
  | 'SCAN_FAILED'
  | 'OCR_FAILED'
  | 'PROCESSING_TIMEOUT'
  | 'REDACTION_FAILED'
  | 'REDACTION_VERIFICATION_FAILED'
  | 'VALUE_UNRECOVERABLE'
  | 'RATE_LIMITED'
  | 'DEPENDENCY_UNAVAILABLE'
  | 'SERVER_ERROR';

export interface ApiErrorInit {
  kind: ApiErrorKind;
  status?: number | null;
  code?: string | null;
  message?: string;
  fieldErrors?: FieldErrors;
  requestId?: string | null;
}

/**
 * The only error type UI code needs to understand.
 * `message` is always safe to display — backend stack traces never reach it.
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /** Backend error code when provided (e.g. DUPLICATE_DOCUMENT). */
  readonly code: string | null;
  readonly fieldErrors: FieldErrors;
  readonly requestId: string | null;

  constructor(init: ApiErrorInit) {
    super(init.message ?? DEFAULT_MESSAGES[init.kind]);
    this.name = 'ApiError';
    this.kind = init.kind;
    this.status = init.status ?? null;
    this.code = init.code ?? null;
    this.fieldErrors = init.fieldErrors ?? {};
    this.requestId = init.requestId ?? null;
  }

  get isRetryable(): boolean {
    return ['network', 'timeout', 'server', 'rate_limited', 'unknown'].includes(this.kind);
  }
}

export function defaultMessageFor(kind: ApiErrorKind): string {
  return DEFAULT_MESSAGES[kind];
}

export function kindFromStatus(status: number): ApiErrorKind {
  if (status === 400 || status === 415 || status === 422) return 'validation';
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 413) return 'payload_too_large';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'server';
  return 'unknown';
}

const CODE_KINDS: Partial<Record<string, ApiErrorKind>> = {
  VALIDATION_ERROR: 'validation',
  INVALID_FILE: 'validation',
  UNSUPPORTED_FILE_TYPE: 'validation',
  VALUE_UNRECOVERABLE: 'validation',
  INVALID_CREDENTIALS: 'unauthorized',
  UNAUTHORIZED: 'unauthorized',
  TOKEN_EXPIRED: 'unauthorized',
  FORBIDDEN: 'forbidden',
  CSRF_FAILED: 'forbidden',
  NOT_FOUND: 'not_found',
  CONFLICT: 'conflict',
  DUPLICATE_DOCUMENT: 'conflict',
  SCAN_IN_PROGRESS: 'conflict',
  DOCUMENT_TOO_LARGE: 'payload_too_large',
  RATE_LIMITED: 'rate_limited',
  DEPENDENCY_UNAVAILABLE: 'server',
  SERVER_ERROR: 'server',
};

export function kindFromResponse(status: number, code: string | null): ApiErrorKind {
  return (code && CODE_KINDS[code]) || kindFromStatus(status);
}

interface FastApiValidationItem {
  loc?: unknown;
  msg?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export interface ParsedError {
  code: string | null;
  message: string | null;
  fieldErrors: FieldErrors;
  requestId: string | null;
}

/**
 * Reads the backend error envelope `{ error: { code, message, details: [{field, message}], requestId } }`.
 * Falls back to a bare FastAPI `{ detail }` body (e.g. from a proxy or an older backend).
 */
export function parseErrorBody(body: unknown): ParsedError {
  const result: ParsedError = { code: null, message: null, fieldErrors: {}, requestId: null };
  if (!isRecord(body)) return result;

  if (isRecord(body.error)) {
    const error = body.error;
    result.code = typeof error.code === 'string' ? error.code : null;
    result.message = typeof error.message === 'string' ? error.message : null;
    result.requestId = typeof error.requestId === 'string' ? error.requestId : null;
    if (Array.isArray(error.details)) {
      for (const item of error.details) {
        if (isRecord(item) && typeof item.field === 'string' && typeof item.message === 'string') {
          result.fieldErrors[item.field] ??= item.message;
        }
      }
    }
    return result;
  }

  const detail = body.detail;
  if (typeof detail === 'string') {
    result.message = detail;
  } else if (Array.isArray(detail)) {
    for (const item of detail as FastApiValidationItem[]) {
      if (!isRecord(item) || typeof item.msg !== 'string') continue;
      const loc = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body' && part !== 'query') : [];
      const field = loc.length > 0 ? String(loc[loc.length - 1]) : '_';
      result.fieldErrors[field] ??= item.msg;
    }
  }
  return result;
}

/** Backend messages are shown for client errors only, and only when short and plain. Never for 5xx. */
export function safeBackendMessage(kind: ApiErrorKind, status: number, message: string | null): string | undefined {
  if (!message || status >= 500) return undefined;
  const displayable: ApiErrorKind[] = [
    'validation',
    'conflict',
    'forbidden',
    'not_found',
    'payload_too_large',
    'rate_limited',
    'unauthorized',
  ];
  if (!displayable.includes(kind)) return undefined;
  if (message.length > 200 || /traceback|exception|\bat\s+\w+\.|\n/i.test(message)) return undefined;
  return message;
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError({ kind: 'unknown' });
}
