import type { ApiKey, CreatedApiKey } from '../types/apiKey';
import { api } from './api';

export interface ApiKeyService {
  list(signal?: AbortSignal): Promise<ApiKey[]>;
  create(name: string): Promise<CreatedApiKey>;
  revoke(id: string): Promise<void>;
}

export const apiKeyApi: ApiKeyService = {
  list: (signal) => api.get('/api-keys', { signal }),
  create: (name) => api.post('/api-keys', { name }),
  revoke: (id) => api.delete(`/api-keys/${encodeURIComponent(id)}`),
};
