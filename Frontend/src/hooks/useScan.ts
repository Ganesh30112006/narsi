import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiError } from '../services/apiError';
import { toApiError } from '../services/apiError';
import { scanApi } from '../services/scanApi';
import type { Scan, ScanStatus } from '../types/scan';

const ACTIVE: ReadonlySet<ScanStatus> = new Set(['QUEUED', 'PROCESSING']);
const POLL_INTERVAL_MS = 1500;
const MAX_BACKOFF_MS = 15_000;

export interface ScanState {
  scan: Scan | undefined;
  status: 'loading' | 'success' | 'error';
  error: ApiError | null;
  /** A poll failed but we still have the last known scan state and will keep trying. */
  pollError: ApiError | null;
  isActive: boolean;
  reload(): void;
}

/**
 * Loads a scan and polls its lightweight status endpoint while it is queued or processing.
 * Polling pauses while the tab is hidden and backs off on transient errors.
 */
export function useScan(scanId: string | undefined): ScanState {
  const [scan, setScan] = useState<Scan | undefined>(undefined);
  const [status, setStatus] = useState<ScanState['status']>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [pollError, setPollError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const scanRef = useRef<Scan | undefined>(undefined);

  useEffect(() => {
    if (!scanId) return;
    const controller = new AbortController();
    let timer: number | undefined;
    let failures = 0;

    const schedule = (delay: number) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(poll, delay);
    };

    const fetchFull = async () => {
      const full = await scanApi.getScan(scanId, controller.signal);
      scanRef.current = full;
      setScan(full);
      return full;
    };

    async function poll() {
      if (controller.signal.aborted) return;
      if (document.visibilityState === 'hidden') {
        schedule(POLL_INTERVAL_MS * 2);
        return;
      }
      try {
        const snapshot = await scanApi.getScanStatus(scanId as string, controller.signal);
        failures = 0;
        setPollError(null);
        if (!ACTIVE.has(snapshot.status)) {
          // Terminal: fetch the full record (summary, report id).
          await fetchFull();
          return;
        }
        const next = scanRef.current ? { ...scanRef.current, ...snapshot } : undefined;
        scanRef.current = next;
        if (next) setScan(next);
        schedule(POLL_INTERVAL_MS);
      } catch (caught) {
        if (controller.signal.aborted) return;
        const apiError = toApiError(caught);
        if (apiError.kind === 'cancelled') return;
        if (!apiError.isRetryable) {
          setError(apiError);
          setStatus('error');
          return;
        }
        failures += 1;
        setPollError(apiError);
        schedule(Math.min(POLL_INTERVAL_MS * 2 ** failures, MAX_BACKOFF_MS));
      }
    }

    setStatus('loading');
    setError(null);
    fetchFull()
      .then((full) => {
        setStatus('success');
        if (ACTIVE.has(full.status)) schedule(POLL_INTERVAL_MS);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        const apiError = toApiError(caught);
        if (apiError.kind === 'cancelled') return;
        setError(apiError);
        setStatus('error');
      });

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [scanId, reloadToken]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  return {
    scan,
    status,
    error,
    pollError,
    isActive: scan ? ACTIVE.has(scan.status) : false,
    reload,
  };
}
