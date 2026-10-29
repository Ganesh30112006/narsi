import type { PublicRedactionAction, PublicResult, PublicUpload } from '../types/public';
import type { Redaction } from '../types/redaction';
import type { ReportExportFormat } from '../types/report';
import type { ScanStatusSnapshot } from '../types/scan';
import type { DownloadResult, RequestOptions } from './api';
import { api } from './api';

/** No sign-in: every request after the upload carries that upload's access token instead of a session. */
function withToken(token: string, extra: RequestOptions = {}): RequestOptions {
  return { ...extra, headers: { 'X-Access-Token': token }, skipAuthHandling: true };
}

const scanPath = (scanId: string) => `/public/scans/${encodeURIComponent(scanId)}`;

export interface PublicService {
  upload(file: File, onProgress?: (fraction: number) => void): Promise<PublicUpload>;
  getStatus(scanId: string, token: string, signal?: AbortSignal): Promise<ScanStatusSnapshot>;
  getResult(scanId: string, token: string, signal?: AbortSignal): Promise<PublicResult>;
  /** Creates a redacted copy of the whole file (every finding redacted or masked). */
  createRedaction(scanId: string, token: string, action: PublicRedactionAction): Promise<Redaction>;
  downloadRedaction(scanId: string, token: string): Promise<DownloadResult>;
  downloadReport(scanId: string, token: string, format: ReportExportFormat): Promise<DownloadResult>;
  /** Deletes the upload, its results and any redacted copy immediately. */
  remove(scanId: string, token: string): Promise<void>;
}

export const publicApi: PublicService = {
  upload: (file, onProgress) => {
    const form = new FormData();
    form.append('file', file);
    return api.upload<PublicUpload>('/public/uploads', form, { onProgress, skipAuthHandling: true });
  },
  getStatus: (scanId, token, signal) => api.get(`${scanPath(scanId)}/status`, withToken(token, { signal })),
  getResult: (scanId, token, signal) => api.get(scanPath(scanId), withToken(token, { signal })),
  createRedaction: (scanId, token, action) => api.post(`${scanPath(scanId)}/redaction`, { action }, withToken(token)),
  downloadRedaction: (scanId, token) => api.download(`${scanPath(scanId)}/redaction/download`, withToken(token)),
  downloadReport: (scanId, token, format) => api.download(`${scanPath(scanId)}/report`, withToken(token, { query: { format } })),
  remove: (scanId, token) => api.delete(scanPath(scanId), withToken(token)),
};
