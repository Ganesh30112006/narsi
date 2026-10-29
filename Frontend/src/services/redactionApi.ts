import type { Redaction, RedactionRequest } from '../types/redaction';
import { api } from './api';

export interface RedactionService {
  /** Creates a sanitized copy. The original document is never modified. */
  create(request: RedactionRequest): Promise<Redaction>;
  get(redactionId: string, signal?: AbortSignal): Promise<Redaction>;
}

export const redactionApi: RedactionService = {
  create: (request) => api.post('/redactions', request),
  get: (redactionId, signal) => api.get(`/redactions/${encodeURIComponent(redactionId)}`, { signal }),
};
