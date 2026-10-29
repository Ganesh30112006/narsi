import type { ReactNode } from 'react';
import styles from './Badge.module.css';

export type BadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'outline';

interface BadgeProps {
  tone?: BadgeTone;
  icon?: ReactNode;
  pulse?: boolean;
  title?: string;
  className?: string;
  children: ReactNode;
}

export function Badge({ tone = 'neutral', icon, pulse, title, className, children }: BadgeProps) {
  return (
    <span className={[styles.badge, styles[tone], pulse && styles.pulse, className].filter(Boolean).join(' ')} title={title}>
      {icon}
      {children}
    </span>
  );
}
