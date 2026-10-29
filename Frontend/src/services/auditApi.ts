import type { Paginated } from '../types/api';
import type { AuditLog, AuditQuery } from '../types/audit';
import type { QueryParams } from './api';
import { api } from './api';

export interface AuditService {
  list(query: AuditQuery, signal?: AbortSignal): Promise<Paginated<AuditLog>>;
}

export const auditApi: AuditService = {
  list: (query, signal) => api.getPage('/audit-logs', { query: { ...query } as QueryParams, signal }),
};
