import { formatNumber, formatPercent } from '../../utils/formatting';
import styles from './Charts.module.css';

export interface StackSegment {
  key: string;
  label: string;
  value: number;
  /** A token name, e.g. `--chart-high`. */
  colorVar: string;
}

interface StackedBarProps {
  segments: StackSegment[];
  label: string;
}

/** One proportional bar with a text legend (label, count, share) — identity never relies on color alone. */
export function StackedBar({ segments, label }: StackedBarProps) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  return (
    <figure className={styles.stacked}>
      <div className={styles.stackTrack} aria-hidden>
        {total > 0 &&
          segments
            .filter((segment) => segment.value > 0)
            .map((segment) => (
              <span
                key={segment.key}
                className={styles.stackSegment}
                style={{ flexGrow: segment.value, background: `var(${segment.colorVar})` }}
                title={`${segment.label}: ${formatNumber(segment.value)} (${formatPercent(segment.value / total)})`}
              />
            ))}
      </div>
      <figcaption className="visually-hidden">{label}</figcaption>
      <ul className={styles.legend} aria-label={label}>
        {segments.map((segment) => (
          <li key={segment.key}>
            <span className={styles.legendSwatch} style={{ background: `var(${segment.colorVar})` }} aria-hidden />
            <span className={styles.legendLabel}>{segment.label}</span>
            <span className={styles.legendValue}>{formatNumber(segment.value)}</span>
            <span className={styles.legendShare}>{total > 0 ? formatPercent(segment.value / total) : '—'}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
