import type { Paginated } from '../types/api';
import type { Report, ReportExportFormat, ReportQuery, ReportSummary } from '../types/report';
import type { DownloadResult, QueryParams } from './api';
import { api } from './api';

export interface ReportService {
  list(query: ReportQuery, signal?: AbortSignal): Promise<Paginated<ReportSummary>>;
  get(reportId: string, signal?: AbortSignal): Promise<Report>;
  export(reportId: string, format: ReportExportFormat): Promise<DownloadResult>;
}

export const reportApi: ReportService = {
  list: (query, signal) => api.getPage('/reports', { query: { ...query } as QueryParams, signal }),
  get: (reportId, signal) => api.get(`/reports/${encodeURIComponent(reportId)}`, { signal }),
  export: (reportId, format) =>
    api.download(`/reports/${encodeURIComponent(reportId)}/download`, { query: { format }, timeoutMs: 120_000 }),
};
