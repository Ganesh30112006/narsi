import type { Paginated } from '../types/api';
import type { Finding, FindingQuery, RevealedValue, RevealRequest } from '../types/finding';
import type { QueryParams } from './api';
import { api } from './api';

export interface FindingService {
  list(query: FindingQuery, signal?: AbortSignal): Promise<Paginated<Finding>>;
  get(findingId: string, signal?: AbortSignal): Promise<Finding>;
  /** Audited, permission-controlled reveal of the raw value. */
  reveal(findingId: string, request: RevealRequest): Promise<RevealedValue>;
}

export const findingApi: FindingService = {
  list: (query, signal) => api.getPage('/findings', { query: { ...query } as QueryParams, signal }),
  get: (findingId, signal) => api.get(`/findings/${encodeURIComponent(findingId)}`, { signal }),
  reveal: (findingId, request) => api.post(`/findings/${encodeURIComponent(findingId)}/reveal`, request),
};
