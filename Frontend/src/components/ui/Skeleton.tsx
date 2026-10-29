import type { CSSProperties } from 'react';
import styles from './Skeleton.module.css';

interface SkeletonProps {
  width?: CSSProperties['width'];
  height?: CSSProperties['height'];
  radius?: CSSProperties['borderRadius'];
  className?: string;
}

export function Skeleton({ width = '100%', height = 14, radius, className }: SkeletonProps) {
  return (
    <span
      className={[styles.skeleton, className].filter(Boolean).join(' ')}
      style={{ width, height, borderRadius: radius }}
      aria-hidden
    />
  );
}

/** A labelled loading region composed of skeleton lines. */
export function SkeletonBlock({ lines = 3, label = 'Loading' }: { lines?: number; label?: string }) {
  return (
    <div className={styles.block} role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} width={index === lines - 1 ? '60%' : '100%'} />
      ))}
    </div>
  );
}
