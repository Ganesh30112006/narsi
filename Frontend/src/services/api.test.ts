import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { ApiError } from './apiError';
import type { Transport, TransportRequest, TransportResponse } from './transport';
import { TransportFailure } from './transport';

const envelope = (data: unknown, meta: Record<string, unknown> = {}) => ({ data, meta, error: null });
const failure = (code: string, message: string, details: { field: string; message: string }[] = []) => ({
  data: null,
  meta: {},
  error: { code, message, details, requestId: 'req-1' },
});

function clientWith(respond: (request: TransportRequest) => TransportResponse | Promise<TransportResponse>) {
  const transport: Transport = vi.fn(async (request: TransportRequest) => {
    const response = await respond(request);
    return response;
  });
  const client = new ApiClient({ baseUrl: '/api/v1', timeoutMs: 1000, loadTransport: async () => transport });
  return { client, transport };
}

function clientReturning(response: TransportResponse | TransportFailure) {
  return clientWith(() => {
    if (response instanceof TransportFailure) throw response;
    return response;
  });
}

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error('Expected the request to fail');
}

describe('ApiClient', () => {
  it('unwraps the data envelope and builds the URL', async () => {
    const { client, transport } = clientReturning({ status: 200, headers: {}, body: envelope({ id: 'd1' }) });
    await expect(client.get('/documents/d1', { query: { page: 2, search: '', fileType: undefined } })).resolves.toEqual({
      id: 'd1',
    });
    const request = vi.mocked(transport).mock.calls[0]?.[0];
    expect(request?.url).toBe('/api/v1/documents/d1?page=2');
  });

  it('maps paginated envelopes to items and page metadata', async () => {
    const { client } = clientReturning({
      status: 200,
      headers: {},
      body: envelope([{ id: 'a' }, { id: 'b' }], { page: 2, pageSize: 2, total: 5, totalPages: 3 }),
    });
    await expect(client.getPage('/documents')).resolves.toEqual({
      items: [{ id: 'a' }, { id: 'b' }],
      page: 2,
      pageSize: 2,
      total: 5,
    });
  });

  it('converts validation errors into field errors and keeps the backend code', async () => {
    const { client } = clientReturning({
      status: 422,
      headers: {},
      body: failure('VALIDATION_ERROR', "Some of the information provided isn't valid.", [
        { field: 'newPassword', message: 'Too short' },
      ]),
    });
    const error = await captureError(client.post('/auth/change-password', {}));
    expect(error.kind).toBe('validation');
    expect(error.code).toBe('VALIDATION_ERROR');
    expect(error.fieldErrors).toEqual({ newPassword: 'Too short' });
    expect(error.requestId).toBe('req-1');
  });

  it('maps stable codes to kinds (duplicate upload, unsupported type, too large)', async () => {
    const duplicate = await captureError(
      clientReturning({
        status: 409,
        headers: {},
        body: failure('DUPLICATE_DOCUMENT', 'This file has already been uploaded.'),
      }).client.get('/x'),
    );
    expect(duplicate.kind).toBe('conflict');
    expect(duplicate.message).toBe('This file has already been uploaded.');
    const unsupported = await captureError(
      clientReturning({
        status: 415,
        headers: {},
        body: failure('UNSUPPORTED_FILE_TYPE', "This file type isn't supported."),
      }).client.get('/x'),
    );
    expect(unsupported.kind).toBe('validation');
    const tooLarge = await captureError(
      clientReturning({ status: 413, headers: {}, body: failure('DOCUMENT_TOO_LARGE', 'Too big') }).client.get('/x'),
    );
    expect(tooLarge.kind).toBe('payload_too_large');
  });

  it('silently refreshes an expired session and replays the request', async () => {
    let expired = true;
    const { client, transport } = clientWith((request) => {
      if (request.path === '/auth/refresh') {
        expired = false;
        return { status: 200, headers: {}, body: envelope({ id: 'u1' }) };
      }
      if (expired) return { status: 401, headers: {}, body: failure('TOKEN_EXPIRED', 'Your session has expired.') };
      return { status: 200, headers: {}, body: envelope(['ok']) };
    });
    const listener = vi.fn();
    client.onUnauthorized(listener);
    await expect(client.get('/documents')).resolves.toEqual(['ok']);
    expect(listener).not.toHaveBeenCalled();
    expect(vi.mocked(transport).mock.calls.map(([request]) => request.path)).toEqual([
      '/documents',
      '/auth/refresh',
      '/documents',
    ]);
  });

  it('broadcasts session expiry when refresh fails', async () => {
    const { client } = clientWith((request) =>
      request.path === '/auth/refresh'
        ? { status: 401, headers: {}, body: failure('UNAUTHORIZED', 'Your session has expired.') }
        : { status: 401, headers: {}, body: failure('TOKEN_EXPIRED', 'Your session has expired.') },
    );
    const listener = vi.fn();
    client.onUnauthorized(listener);
    const error = await captureError(client.get('/documents'));
    expect(error.kind).toBe('unauthorized');
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('does not refresh or broadcast for login attempts', async () => {
    const { client, transport } = clientReturning({
      status: 401,
      headers: {},
      body: failure('INVALID_CREDENTIALS', 'Incorrect email or password.'),
    });
    const listener = vi.fn();
    client.onUnauthorized(listener);
    const error = await captureError(client.post('/auth/login', {}, { skipAuthHandling: true }));
    expect(error.message).toBe('Incorrect email or password.');
    expect(listener).not.toHaveBeenCalled();
    expect(vi.mocked(transport)).toHaveBeenCalledTimes(1);
  });

  it('maps 403 and 404 with safe backend messages', async () => {
    const forbidden = await captureError(
      clientReturning({ status: 403, headers: {}, body: failure('FORBIDDEN', 'Role not permitted.') }).client.get('/audit-logs'),
    );
    expect(forbidden.kind).toBe('forbidden');
    expect(forbidden.message).toBe('Role not permitted.');
    const missing = await captureError(clientReturning({ status: 404, headers: {}, body: null }).client.get('/documents/x'));
    expect(missing.kind).toBe('not_found');
    expect(missing.message).toMatch(/couldn't find/);
  });

  it('never exposes server error messages for 500s', async () => {
    const { client } = clientReturning({
      status: 500,
      headers: { 'x-request-id': 'req-123' },
      body: failure('SERVER_ERROR', 'Traceback (most recent call last): File "app.py"'),
    });
    const error = await captureError(client.get('/documents'));
    expect(error.kind).toBe('server');
    expect(error.message).not.toMatch(/Traceback/);
    expect(error.requestId).toBe('req-123');
    expect(error.isRetryable).toBe(true);
  });

  it('still understands bare FastAPI error bodies', async () => {
    const { client } = clientReturning({
      status: 422,
      headers: {},
      body: { detail: [{ loc: ['body', 'email'], msg: 'Invalid email', type: 'value_error' }] },
    });
    expect((await captureError(client.post('/auth/login', {}))).fieldErrors).toEqual({ email: 'Invalid email' });
  });

  it('reports network failures and timeouts distinctly', async () => {
    const network = await captureError(clientReturning(new TransportFailure('network')).client.get('/documents'));
    expect(network.kind).toBe('network');
    const timeout = await captureError(clientReturning(new TransportFailure('timeout')).client.get('/documents'));
    expect(timeout.kind).toBe('timeout');
    const cancelled = await captureError(clientReturning(new TransportFailure('aborted')).client.get('/documents'));
    expect(cancelled.kind).toBe('cancelled');
  });

  it('sends the CSRF token cookie on mutating requests', async () => {
    document.cookie = 'csrf_token=abc123';
    const { client, transport } = clientReturning({ status: 204, headers: {}, body: null });
    await client.delete('/documents/1');
    expect(vi.mocked(transport).mock.calls[0]?.[0].headers['X-CSRF-Token']).toBe('abc123');
    document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  });
});
