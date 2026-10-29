import { Check, Minus, X } from 'lucide-react';
import type { ScanProgress, ScanStageProgress, StageState } from '../../types/scan';
import { formatTime } from '../../utils/formatting';
import { SCAN_STAGE_DESCRIPTIONS, SCAN_STAGE_LABELS } from '../../utils/labels';
import { ProgressBar } from '../ui/ProgressBar';
import styles from './Scans.module.css';

const STATE_TEXT: Record<StageState, string> = {
  PENDING: 'Pending',
  ACTIVE: 'In progress',
  COMPLETED: 'Done',
  SKIPPED: 'Not needed',
  FAILED: 'Failed',
};

function Marker({ state }: { state: StageState }) {
  return (
    <span className={styles.marker} aria-hidden>
      {state === 'COMPLETED' && <Check size={13} strokeWidth={3} />}
      {state === 'FAILED' && <X size={13} strokeWidth={3} />}
      {state === 'SKIPPED' && <Minus size={12} />}
    </span>
  );
}

interface ScanTimelineProps {
  stages: ScanStageProgress[];
  progress: ScanProgress;
}

export function ScanTimeline({ stages, progress }: ScanTimelineProps) {
  const pageText =
    progress.currentPage !== null && progress.totalPages !== null
      ? `Scanning page ${progress.currentPage} of ${progress.totalPages}`
      : null;

  return (
    <ol className={styles.timeline} aria-label="Scan progress">
      {stages.map((step) => (
        <li
          key={step.stage}
          className={styles.step}
          data-state={step.state}
          aria-current={step.state === 'ACTIVE' ? 'step' : undefined}
        >
          <Marker state={step.state} />
          <div className={styles.stepBody}>
            <div className={styles.stepTitle}>
              {SCAN_STAGE_LABELS[step.stage]}
              <span className={styles.stepState}>
                {STATE_TEXT[step.state]}
                {step.state === 'COMPLETED' && step.completedAt ? ` · ${formatTime(step.completedAt)}` : ''}
              </span>
            </div>
            {(step.state === 'ACTIVE' || step.state === 'FAILED') && (
              <p className={styles.stepDescription}>{SCAN_STAGE_DESCRIPTIONS[step.stage]}</p>
            )}
            {step.state === 'ACTIVE' && (
              <div className={styles.stepProgress}>
                <ProgressBar
                  value={progress.percent !== null ? progress.percent / 100 : null}
                  label={`${SCAN_STAGE_LABELS[step.stage]} progress`}
                />
                {pageText && <p className={styles.stepProgressText}>{pageText}</p>}
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
