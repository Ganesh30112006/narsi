import type { ConfidenceLevel } from '../../types/finding';
import { formatPercent } from '../../utils/formatting';
import { CONFIDENCE_LABELS } from '../../utils/labels';
import styles from './Findings.module.css';

interface ConfidenceIndicatorProps {
  confidence: number;
  level: ConfidenceLevel;
  /** Show the level word next to the percentage. */
  showLabel?: boolean;
}

/** Percentage + small meter. The level is always available as text (visible or for screen readers). */
export function ConfidenceIndicator({ confidence, level, showLabel = false }: ConfidenceIndicatorProps) {
  const percent = formatPercent(confidence);
  return (
    <span className={styles.confidence}>
      <span className={styles.confidenceValue}>{percent}</span>
      <span className={styles.meter} data-level={level} aria-hidden>
        <span style={{ width: `${Math.round(confidence * 100)}%` }} />
      </span>
      {showLabel ? (
        <span className={styles.confidenceLabel}>{CONFIDENCE_LABELS[level]}</span>
      ) : (
        <span className="visually-hidden">{CONFIDENCE_LABELS[level]}</span>
      )}
    </span>
  );
}
