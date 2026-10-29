import type { Paginated } from '../types/api';
import { ApiError, kindFromResponse, parseErrorBody, safeBackendMessage } from './apiError';
import type { HttpMethod, ResponseType, Transport, TransportRequest } from './transport';
import { TransportFailure, xhrTransport } from './transport';

export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue>;

export interface RequestOptions {
  query?: QueryParams;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Do not refresh or broadcast session expiry on 401 (used by login, refresh, session restore and public pages). */
  skipAuthHandling?: boolean;
  /** Extra request headers (e.g. the public upload access token). */
  headers?: Record<string, string>;
}

type InternalOptions = RequestOptions & { onUploadProgress?: TransportRequest['onUploadProgress'] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Backend responses are `{ data, meta, error }`. */
function isEnvelope(body: unknown): body is { data: unknown; meta?: Record<string, unknown>; error: unknown } {
  return isRecord(body) && 'data' in body && 'error' in body;
}

export interface UploadOptions extends RequestOptions {
  onProgress?: (fraction: number) => void;
}

export interface DownloadResult {
  blob: Blob;
  fileName: string | null;
}

export interface ApiClientConfig {
  baseUrl: string;
  timeoutMs: number;
  /** Lazy transport loader (lets the mock backend be code-split out of production). */
  loadTransport: () => Promise<Transport>;
}

const MUTATING: ReadonlySet<HttpMethod> = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const CSRF_COOKIE_NAMES = ['csrf_token', 'csrftoken', 'XSRF-TOKEN'];

function readCsrfToken(): string | null {
  if (typeof document === 'undefined' || !document.cookie) return null;
  for (const part of document.cookie.split(';')) {
    const [rawName, ...rest] = part.trim().split('=');
    if (rawName && CSRF_COOKIE_NAMES.includes(rawName)) return decodeURIComponent(rest.join('='));
  }
  return null;
}

function buildQuery(query: QueryParams | undefined): URLSearchParams {
  const params = new URLSearchParams();
  if (!query) return params;
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  return params;
}

function fileNameFromDisposition(header: string | undefined): string | null {
  if (!header) return null;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8?.[1]) return decodeURIComponent(utf8[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1] ?? null;
}

type UnauthorizedListener = () => void;

export class ApiClient {
  private readonly config: ApiClientConfig;
  private transportPromise: Promise<Transport> | null = null;
  private readonly unauthorizedListeners = new Set<UnauthorizedListener>();
  private refreshing: Promise<boolean> | null = null;

  constructor(config: ApiClientConfig) {
    this.config = config;
  }

  /** Subscribe to session expiry (any 401 outside login/session-restore). */
  onUnauthorized(listener: UnauthorizedListener): () => void {
    this.unauthorizedListeners.add(listener);
    return () => {
      this.unauthorizedListeners.delete(listener);
    };
  }

  /** Test hook: replace the transport. */
  setTransport(transport: Transport): void {
    this.transportPromise = Promise.resolve(transport);
  }

  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.send<T>('GET', path, null, 'json', options);
  }

  post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.send<T>('POST', path, body === undefined ? null : JSON.stringify(body), 'json', options);
  }

  put<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return this.send<T>('PUT', path, JSON.stringify(body), 'json', options);
  }

  patch<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return this.send<T>('PATCH', path, JSON.stringify(body), 'json', options);
  }

  delete<T = void>(path: string, options?: RequestOptions): Promise<T> {
    return this.send<T>('DELETE', path, null, 'json', options);
  }

  upload<T>(path: string, formData: FormData, options?: UploadOptions): Promise<T> {
    const onProgress = options?.onProgress;
    return this.send<T>('POST', path, formData, 'json', {
      ...options,
      timeoutMs: options?.timeoutMs ?? Math.max(this.config.timeoutMs, 300_000),
      onUploadProgress: onProgress ? (loaded, total) => onProgress(total > 0 ? loaded / total : 0) : undefined,
    });
  }

  /** GET a paginated list: envelope `data` (items) + `meta` (page, pageSize, total). */
  async getPage<T>(path: string, options?: RequestOptions): Promise<Paginated<T>> {
    const { body } = await this.request('GET', path, null, 'json', options);
    const items = (isEnvelope(body) ? body.data : body) as T[] | null;
    const meta = (isEnvelope(body) ? body.meta : undefined) ?? {};
    const list = Array.isArray(items) ? items : [];
    return {
      items: list,
      page: Number(meta.page ?? 1),
      pageSize: Number(meta.pageSize ?? list.length),
      total: Number(meta.total ?? list.length),
    };
  }

  async download(path: string, options?: RequestOptions): Promise<DownloadResult> {
    const { body, headers } = await this.request('GET', path, null, 'blob', options);
    if (!(body instanceof Blob)) throw new ApiError({ kind: 'unknown', message: 'The file could not be downloaded.' });
    return { blob: body, fileName: fileNameFromDisposition(headers['content-disposition']) };
  }

  private async send<T>(
    method: HttpMethod,
    path: string,
    body: string | FormData | null,
    responseType: ResponseType,
    options?: InternalOptions,
  ): Promise<T> {
    const response = await this.request(method, path, body, responseType, options);
    return (isEnvelope(response.body) ? response.body.data : response.body) as T;
  }

  /**
   * Executes a request. An expired access token triggers one silent refresh and a replay; if the refresh
   * fails, listeners are told the session has ended.
   */
  private async request(
    method: HttpMethod,
    path: string,
    body: string | FormData | null,
    responseType: ResponseType,
    options?: InternalOptions,
  ) {
    try {
      return await this.execute(method, path, body, responseType, options);
    } catch (error) {
      if (!(error instanceof ApiError) || error.kind !== 'unauthorized' || options?.skipAuthHandling) throw error;
      if (error.code === 'TOKEN_EXPIRED' && (await this.refreshSession())) {
        try {
          return await this.execute(method, path, body, responseType, options);
        } catch (retryError) {
          if (retryError instanceof ApiError && retryError.kind === 'unauthorized') this.notifyUnauthorized();
          throw retryError;
        }
      }
      this.notifyUnauthorized();
      throw error;
    }
  }

  /** Single-flight refresh: concurrent requests share one POST /auth/refresh. */
  private refreshSession(): Promise<boolean> {
    this.refreshing ??= this.execute('POST', '/auth/refresh', null, 'json', { skipAuthHandling: true })
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        this.refreshing = null;
      });
    return this.refreshing;
  }

  private notifyUnauthorized(): void {
    this.unauthorizedListeners.forEach((listener) => listener());
  }

  private resolveTransport(): Promise<Transport> {
    this.transportPromise ??= this.config.loadTransport();
    return this.transportPromise;
  }

  private async execute(
    method: HttpMethod,
    path: string,
    body: string | FormData | null,
    responseType: ResponseType,
    options?: InternalOptions,
  ) {
    const query = buildQuery(options?.query);
    const queryString = query.toString();
    const url = `${this.config.baseUrl}${path}${queryString ? `?${queryString}` : ''}`;

    const headers: Record<string, string> = {
      ...options?.headers,
      Accept: responseType === 'blob' ? '*/*' : 'application/json',
    };
    if (typeof body === 'string') headers['Content-Type'] = 'application/json';
    if (MUTATING.has(method)) {
      const csrf = readCsrfToken();
      if (csrf) headers['X-CSRF-Token'] = csrf;
    }

    const transport = await this.resolveTransport();
    let response;
    try {
      response = await transport({
        method,
        url,
        path,
        query,
        headers,
        body,
        responseType,
        timeoutMs: options?.timeoutMs ?? this.config.timeoutMs,
        signal: options?.signal,
        onUploadProgress: options?.onUploadProgress,
      });
    } catch (error) {
      const kind = error instanceof TransportFailure ? (error.reason === 'aborted' ? 'cancelled' : error.reason) : 'network';
      if (kind !== 'cancelled') logRequestFailure(method, path, null, kind);
      throw new ApiError({ kind });
    }

    if (response.status >= 200 && response.status < 300) {
      return response;
    }

    const parsed = parseErrorBody(response.body);
    const kind = kindFromResponse(response.status, parsed.code);
    const error = new ApiError({
      kind,
      status: response.status,
      code: parsed.code,
      message: safeBackendMessage(kind, response.status, parsed.message),
      fieldErrors: parsed.fieldErrors,
      requestId: response.headers['x-request-id'] ?? parsed.requestId,
    });
    if (kind !== 'unauthorized') logRequestFailure(method, path, response.status, kind);
    throw error;
  }
}

/** Development-only diagnostics. Never logs request or response bodies (they may contain PII or credentials). */
function logRequestFailure(method: string, path: string, status: number | null, kind: string): void {
  if (import.meta.env.DEV && import.meta.env.MODE !== 'test') {
    console.warn(`[api] ${method} ${path} failed`, { status, kind });
  }
}

export const API_MODE: 'api' | 'mock' = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'api';

function loadTransport(): Promise<Transport> {
  // Statically replaced by Vite; the mock backend is excluded from production bundles.
  if (import.meta.env.VITE_API_MODE === 'mock') {
    return import('../mocks/mockTransport').then((module) => module.mockTransport);
  }
  return Promise.resolve(xhrTransport);
}

export const api = new ApiClient({
  baseUrl: (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, ''),
  timeoutMs: Number(import.meta.env.VITE_API_TIMEOUT_MS ?? 30_000) || 30_000,
  loadTransport,
});
