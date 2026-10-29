import { findingApi } from '../services/findingApi';
import type { FindingQuery } from '../types/finding';
import { useResource } from './useResource';

export function useFindings(query: FindingQuery, options: { enabled?: boolean } = {}) {
  return useResource(`findings:${JSON.stringify(query)}`, (signal) => findingApi.list(query, signal), options);
}
