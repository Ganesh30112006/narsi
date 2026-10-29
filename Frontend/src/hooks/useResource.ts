import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiError } from '../services/apiError';
import { toApiError } from '../services/apiError';

export type ResourceStatus = 'loading' | 'success' | 'error';

export interface ResourceState<T> {
  status: ResourceStatus;
  /** The latest successful data. Kept while refetching so tables don't flash. */
  data: T | undefined;
  error: ApiError | null;
  /** True while a refetch is in flight and previous data is being shown. */
  isRefreshing: boolean;
  reload(): void;
  /** Local optimistic update of the cached data. */
  setData(updater: (current: T | undefined) => T | undefined): void;
}

interface CacheEntry {
  data: unknown;
  storedAt: number;
}

const cache = new Map<string, CacheEntry>();

export function invalidateResource(prefix: string): void {
  for (const key of cache.keys()) {
    if (key.startsWith(prefix)) cache.delete(key);
  }
}

export interface ResourceOptions {
  /** Skip fetching (e.g. while an id is unknown). */
  enabled?: boolean;
  /** Serve cached data younger than this without refetching (stable data only). */
  staleTimeMs?: number;
}

/**
 * Fetches data identified by `key`. A new key triggers a new request and aborts the previous one.
 * Failures are surfaced as `status: 'error'` — never silently converted into empty results.
 */
export function useResource<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  options: ResourceOptions = {},
): ResourceState<T> {
  const { enabled = true, staleTimeMs = 0 } = options;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const cached = staleTimeMs > 0 ? cache.get(key) : undefined;
  const fresh = cached && Date.now() - cached.storedAt < staleTimeMs;

  const [data, setDataState] = useState<T | undefined>(fresh ? (cached.data as T) : undefined);
  const [status, setStatus] = useState<ResourceStatus>(fresh ? 'success' : 'loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const hasDataRef = useRef(Boolean(fresh));

  useEffect(() => {
    if (!enabled) return;
    const entry = staleTimeMs > 0 ? cache.get(key) : undefined;
    if (reloadToken === 0 && entry && Date.now() - entry.storedAt < staleTimeMs) {
      setDataState(entry.data as T);
      hasDataRef.current = true;
      setStatus('success');
      return;
    }

    const controller = new AbortController();
    if (hasDataRef.current) setIsRefreshing(true);
    else setStatus('loading');
    setError(null);

    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        if (staleTimeMs > 0) cache.set(key, { data: result, storedAt: Date.now() });
        hasDataRef.current = true;
        setDataState(result);
        setStatus('success');
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        const apiError = toApiError(caught);
        if (apiError.kind === 'cancelled') return;
        setError(apiError);
        setStatus('error');
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsRefreshing(false);
      });

    return () => controller.abort();
  }, [key, enabled, reloadToken, staleTimeMs]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  const setData = useCallback(
    (updater: (current: T | undefined) => T | undefined) => {
      setDataState((current) => {
        const next = updater(current);
        if (staleTimeMs > 0 && next !== undefined) cache.set(key, { data: next, storedAt: Date.now() });
        return next;
      });
    },
    [key, staleTimeMs],
  );

  return { status, data, error, isRefreshing, reload, setData };
}
