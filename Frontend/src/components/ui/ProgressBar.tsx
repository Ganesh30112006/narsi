import styles from './Misc.module.css';

interface ProgressBarProps {
  /** 0–1. Omit for an indeterminate bar. */
  value?: number | null;
  label: string;
  tone?: 'accent' | 'success' | 'danger';
  size?: 'sm' | 'md';
}

export function ProgressBar({ value, label, tone = 'accent', size = 'sm' }: ProgressBarProps) {
  const determinate = value !== null && value !== undefined;
  const percent = determinate ? Math.round(Math.min(1, Math.max(0, value)) * 100) : undefined;
  return (
    <div
      className={[styles.progress, size === 'md' && styles.progressMd].filter(Boolean).join(' ')}
      role="progressbar"
      aria-label={label}
      aria-valuemin={determinate ? 0 : undefined}
      aria-valuemax={determinate ? 100 : undefined}
      aria-valuenow={percent}
    >
      <div
        className={[styles.progressFill, styles[`progress_${tone}`], !determinate && styles.progressIndeterminate]
          .filter(Boolean)
          .join(' ')}
        style={determinate ? { width: `${percent}%` } : undefined}
      />
    </div>
  );
}
