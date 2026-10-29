import { Skeleton } from '../ui/Skeleton';
import styles from './PageSkeleton.module.css';

/** Structure-shaped placeholder while a lazy route loads. */
export function PageSkeleton() {
  return (
    <div className={styles.page} role="status" aria-label="Loading page">
      <div className={styles.header}>
        <Skeleton width={220} height={24} />
        <Skeleton width={360} height={14} />
      </div>
      <Skeleton height={112} radius={8} />
      <div className={styles.lines}>
        <Skeleton height={14} />
        <Skeleton height={14} />
        <Skeleton width="70%" height={14} />
      </div>
    </div>
  );
}
