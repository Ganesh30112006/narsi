import type { ReactNode } from 'react';
import { formatNumber, formatPercent } from '../../utils/formatting';
import styles from './Charts.module.css';

export interface BarDatum {
  key: string;
  label: ReactNode;
  /** Plain-text label for tooltips and screen readers. */
  text: string;
  value: number;
}

interface BarListProps {
  data: BarDatum[];
  /** Accessible name for the chart, e.g. "Findings by PII type". */
  label: string;
  unit?: { singular: string; plural: string };
  /** Hide rows with a zero value. */
  hideZero?: boolean;
}

/**
 * Horizontal single-series bar list. Magnitude uses one hue; every value is also shown as text,
 * so the list itself is the accessible table view.
 */
export function BarList({ data, label, unit = { singular: 'finding', plural: 'findings' }, hideZero = false }: BarListProps) {
  const rows = hideZero ? data.filter((row) => row.value > 0) : data;
  const max = Math.max(1, ...rows.map((row) => row.value));
  const total = rows.reduce((sum, row) => sum + row.value, 0);

  return (
    <ul className={styles.barList} aria-label={label}>
      {rows.map((row) => {
        const share = total > 0 ? row.value / total : 0;
        const tooltip = `${row.text}: ${formatNumber(row.value)} ${row.value === 1 ? unit.singular : unit.plural} (${formatPercent(share)})`;
        return (
          <li key={row.key} className={styles.barRow}>
            <span className={styles.barLabel}>{row.label}</span>
            <span className={styles.barTrack} aria-hidden>
              {row.value > 0 && <span className={styles.bar} style={{ width: `${(row.value / max) * 100}%` }} />}
            </span>
            <span className={styles.barValue}>
              {formatNumber(row.value)}
              <span className="visually-hidden"> {row.value === 1 ? unit.singular : unit.plural}</span>
            </span>
            <span className={styles.barTooltip} aria-hidden>
              {tooltip}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
