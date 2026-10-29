import type { ConfidenceSummary as Summary } from '../../types/finding';
import { formatNumber } from '../../utils/formatting';
import { ConfidenceBadge } from '../ui/StatusBadge';
import styles from './Findings.module.css';

export function ConfidenceSummary({ summary }: { summary: Summary }) {
  const rows = [
    { level: 'HIGH' as const, count: summary.high },
    { level: 'MEDIUM' as const, count: summary.medium },
    { level: 'LOW' as const, count: summary.low },
  ];
  return (
    <dl className={styles.summary}>
      {rows.map((row) => (
        <div key={row.level} className={styles.summaryRow}>
          <dt>
            <ConfidenceBadge level={row.level} />
          </dt>
          <dd className="tabular">{formatNumber(row.count)}</dd>
        </div>
      ))}
    </dl>
  );
}
