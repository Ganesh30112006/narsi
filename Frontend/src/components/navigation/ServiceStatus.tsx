import { useEffect, useState } from 'react';
import { systemApi } from '../../services/systemApi';
import type { ServiceHealth } from '../../types/api';
import { degradedSummary } from '../../utils/health';
import styles from './Navigation.module.css';

type DisplayStatus = 'checking' | ServiceHealth;

const LABELS: Record<DisplayStatus, string> = {
  checking: 'Checking service…',
  healthy: 'Service operational',
  degraded: 'Service degraded',
  unavailable: 'Service unavailable',
  unknown: 'Service status unknown',
};

const REFRESH_MS = 60_000;

/**
 * Reports what the health endpoint actually says. If it cannot be reached we say so —
 * we never claim the service is operational without evidence.
 */
export function ServiceStatus() {
  const [status, setStatus] = useState<DisplayStatus>('checking');
  const [problems, setProblems] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const check = () => {
      systemApi
        .getHealth(controller.signal)
        .then((health) => {
          setStatus(health.status);
          setProblems(degradedSummary(health.checks));
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setStatus('unavailable');
            setProblems([]);
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) timer = window.setTimeout(check, REFRESH_MS);
        });
    };
    check();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  // Which parts are affected, and why: on hover, and read out with the status.
  const details = problems.join('\n');
  return (
    <div className={styles.serviceStatus} role="status" aria-live="polite" title={details || undefined}>
      <span className={[styles.statusDot, styles[`dot_${status}`]].join(' ')} aria-hidden />
      {LABELS[status]}
      {problems.length > 0 && <span className={styles.visuallyHidden}>. {problems.join('. ')}</span>}
    </div>
  );
}
