import type { HealthStatus } from '../types/api';
import type { DashboardSummary } from '../types/dashboard';
import type { ScanSettings } from '../types/settings';
import { api } from './api';

export interface SystemService {
  getDashboardSummary(signal?: AbortSignal): Promise<DashboardSummary>;
  getHealth(signal?: AbortSignal): Promise<HealthStatus>;
  getSettings(signal?: AbortSignal): Promise<ScanSettings>;
  updateSettings(settings: ScanSettings): Promise<ScanSettings>;
}

export const systemApi: SystemService = {
  getDashboardSummary: (signal) => api.get('/dashboard/summary', { signal }),
  getHealth: (signal) => api.get('/health', { signal, timeoutMs: 8_000, skipAuthHandling: true }),
  getSettings: (signal) => api.get('/settings', { signal }),
  updateSettings: (settings) => api.put('/settings', settings),
};
