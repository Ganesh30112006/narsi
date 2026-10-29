import type { PIIType } from '../../types/finding';
import { PII_TYPE_DESCRIPTIONS, PII_TYPE_LABELS } from '../../utils/labels';
import styles from './Findings.module.css';

/** PII category label with a restrained category swatch. The text carries the meaning. */
export function FindingBadge({ type }: { type: PIIType }) {
  return (
    <span className={styles.piiBadge} title={PII_TYPE_DESCRIPTIONS[type]}>
      <span className={styles.piiSwatch} data-pii={type} aria-hidden />
      {PII_TYPE_LABELS[type]}
    </span>
  );
}
