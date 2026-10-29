import { Link } from 'react-router';
import type { AuditLog } from '../../types/audit';
import { formatDateTime } from '../../utils/formatting';
import { auditActionLabel, auditRoleLabel } from '../../utils/labels';
import { AuditResultBadge } from '../ui/StatusBadge';
import { DataTable } from '../ui/Table';
import styles from './Audit.module.css';

interface AuditTableProps {
  entries: AuditLog[] | undefined;
  loading?: boolean;
  refreshing?: boolean;
}

export function AuditTable({ entries, loading, refreshing }: AuditTableProps) {
  return (
    <DataTable
      caption="Audit log"
      rows={entries}
      getRowId={(entry) => entry.id}
      loading={loading}
      refreshing={refreshing}
      skeletonRows={10}
      columns={[
        {
          id: 'timestamp',
          header: 'Timestamp',
          cell: (entry) => (
            <time dateTime={entry.timestamp} className="tabular secondary">
              {formatDateTime(entry.timestamp)}
            </time>
          ),
          nowrap: true,
        },
        {
          id: 'user',
          header: 'User',
          cell: (entry) => (
            <span className={styles.user}>
              <span className={styles.userName}>{entry.user.name}</span>
              <span className={styles.userRole}>{auditRoleLabel(entry.user.role)}</span>
            </span>
          ),
        },
        {
          id: 'action',
          header: 'Action',
          cell: (entry) => (
            <span className={styles.action}>
              {auditActionLabel(entry.action)}
              {entry.details && <span className={styles.details}>{entry.details}</span>}
            </span>
          ),
        },
        {
          id: 'document',
          header: 'Document',
          cell: (entry) =>
            entry.documentName ? (
              entry.documentId ? (
                <Link to={`/app/documents/${entry.documentId}`} className={styles.document}>
                  {entry.documentName}
                </Link>
              ) : (
                <span className={styles.document}>{entry.documentName}</span>
              )
            ) : (
              <span className="muted">—</span>
            ),
          hideBelow: 'mobile',
        },
        { id: 'result', header: 'Result', cell: (entry) => <AuditResultBadge result={entry.result} />, nowrap: true },
      ]}
    />
  );
}
