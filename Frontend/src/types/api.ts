export type SortOrder = 'asc' | 'desc';

export interface Pagination {
  page: number;
  pageSize: number;
  total: number;
}

export interface Paginated<T> extends Pagination {
  items: T[];
}

export interface PageQuery {
  page?: number;
  pageSize?: number;
}

export type ApiErrorKind =
  | 'unauthorized'
  | 'forbidden'
  | 'validation'
  | 'not_found'
  | 'conflict'
  | 'payload_too_large'
  | 'rate_limited'
  | 'server'
  | 'network'
  | 'timeout'
  | 'cancelled'
  | 'unknown';

/** Field-level validation messages keyed by field name (from FastAPI 422 `detail`). */
export type FieldErrors = Record<string, string>;

export type ServiceHealth = 'healthy' | 'degraded' | 'unavailable' | 'unknown';

export interface HealthCheck {
  name: string;
  status: ServiceHealth;
  detail?: string | null;
  critical: boolean;
}

export interface HealthStatus {
  status: ServiceHealth;
  checkedAt: string;
  version: string | null;
  checks?: HealthCheck[];
}
