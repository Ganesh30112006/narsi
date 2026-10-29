export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export type ResponseType = 'json' | 'blob';

export interface TransportRequest {
  method: HttpMethod;
  /** Fully-qualified URL including base and query string. */
  url: string;
  /** Path relative to the API base, without query string (e.g. `/documents/abc`). */
  path: string;
  query: URLSearchParams;
  headers: Record<string, string>;
  body: string | FormData | null;
  responseType: ResponseType;
  timeoutMs: number;
  signal?: AbortSignal;
  onUploadProgress?: (loaded: number, total: number) => void;
}

export interface TransportResponse {
  status: number;
  /** Lower-cased header names. */
  headers: Record<string, string>;
  /** Parsed JSON, a Blob (for successful blob requests), or null. */
  body: unknown;
}

export type TransportFailureReason = 'network' | 'timeout' | 'aborted';

export class TransportFailure extends Error {
  readonly reason: TransportFailureReason;

  constructor(reason: TransportFailureReason) {
    super(`Transport failure: ${reason}`);
    this.name = 'TransportFailure';
    this.reason = reason;
  }
}

export type Transport = (request: TransportRequest) => Promise<TransportResponse>;

function parseHeaders(raw: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of raw.trim().split(/[\r\n]+/)) {
    const index = line.indexOf(':');
    if (index <= 0) continue;
    headers[line.slice(0, index).trim().toLowerCase()] = line.slice(index + 1).trim();
  }
  return headers;
}

function parseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

/**
 * XHR-based transport. XHR (rather than fetch) is used so uploads can report progress.
 * Cookies are always sent so HTTP-only session cookies work.
 */
export const xhrTransport: Transport = (request) =>
  new Promise<TransportResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(request.method, request.url, true);
    xhr.withCredentials = true;
    xhr.timeout = request.timeoutMs;
    xhr.responseType = request.responseType === 'blob' ? 'blob' : 'text';

    for (const [name, value] of Object.entries(request.headers)) {
      xhr.setRequestHeader(name, value);
    }

    if (request.onUploadProgress) {
      const onProgress = request.onUploadProgress;
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      };
    }

    const onAbort = () => xhr.abort();
    request.signal?.addEventListener('abort', onAbort, { once: true });
    const cleanup = () => request.signal?.removeEventListener('abort', onAbort);

    xhr.onload = () => {
      cleanup();
      const headers = parseHeaders(xhr.getAllResponseHeaders());
      const status = xhr.status;
      if (request.responseType === 'blob') {
        const blob = xhr.response as Blob | null;
        if (status >= 200 && status < 300) {
          resolve({ status, headers, body: blob });
          return;
        }
        // Error bodies of blob requests are JSON; decode them for error conversion.
        if (blob) {
          blob
            .text()
            .then((text) => resolve({ status, headers, body: parseJson(text) }))
            .catch(() => resolve({ status, headers, body: null }));
        } else {
          resolve({ status, headers, body: null });
        }
        return;
      }
      resolve({ status, headers, body: parseJson(xhr.responseText) });
    };
    xhr.onerror = () => {
      cleanup();
      reject(new TransportFailure('network'));
    };
    xhr.ontimeout = () => {
      cleanup();
      reject(new TransportFailure('timeout'));
    };
    xhr.onabort = () => {
      cleanup();
      reject(new TransportFailure('aborted'));
    };

    if (request.signal?.aborted) {
      xhr.abort();
      return;
    }
    xhr.send(request.body);
  });
