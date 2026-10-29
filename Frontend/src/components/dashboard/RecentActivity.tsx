import { Link } from 'react-router';
import type { AuditLog } from '../../types/audit';
import { formatDateTime, formatRelativeTime } from '../../utils/formatting';
import { AUDIT_RESULT_LABELS, auditActionLabel } from '../../utils/labels';
import styles from './Dashboard.module.css';

export function RecentActivity({ entries }: { entries: AuditLog[] }) {
  return (
    <ol className={styles.activity}>
      {entries.map((entry) => (
        <li key={entry.id} className={styles.activityItem}>
          <span className={styles.activityDot} data-result={entry.result} aria-hidden />
          <div className={styles.activityBody}>
            <p className={styles.activityAction}>
              {auditActionLabel(entry.action)}
              {entry.result !== 'SUCCESS' && (
                <span className={styles.activityResult}> · {AUDIT_RESULT_LABELS[entry.result]}</span>
              )}
              {entry.documentName && (
                <>
                  <span className={styles.activitySeparator} aria-hidden>
                    {' '}
                    ·{' '}
                  </span>
                  {entry.documentId ? (
                    <Link to={`/app/documents/${entry.documentId}`} className={styles.activityDocument}>
                      {entry.documentName}
                    </Link>
                  ) : (
                    <span className={styles.activityDocument}>{entry.documentName}</span>
                  )}
                </>
              )}
            </p>
            <p className={styles.activityMeta}>
              {entry.user.name} ·{' '}
              <time dateTime={entry.timestamp} title={formatDateTime(entry.timestamp)}>
                {formatRelativeTime(entry.timestamp)}
              </time>
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
