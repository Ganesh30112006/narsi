import type { CreateScanRequest, Scan, ScanStatusSnapshot } from '../types/scan';
import { api } from './api';

export interface ScanService {
  createScan(request: CreateScanRequest): Promise<Scan>;
  getScan(scanId: string, signal?: AbortSignal): Promise<Scan>;
  getScanStatus(scanId: string, signal?: AbortSignal): Promise<ScanStatusSnapshot>;
  /** Re-queues a failed scan (same scan id, next attempt). */
  retryScan(scanId: string): Promise<Scan>;
}

export const scanApi: ScanService = {
  createScan: (request) => api.post('/scans', request),
  getScan: (scanId, signal) => api.get(`/scans/${encodeURIComponent(scanId)}`, { signal }),
  getScanStatus: (scanId, signal) => api.get(`/scans/${encodeURIComponent(scanId)}/status`, { signal }),
  retryScan: (scanId) => api.post(`/scans/${encodeURIComponent(scanId)}/retry`),
};
