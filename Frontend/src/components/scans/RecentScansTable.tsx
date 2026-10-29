import { Link } from 'react-router';
import type { ScanListItem } from '../../types/scan';
import { formatNumber, formatRelativeTime } from '../../utils/formatting';
import { ButtonLink } from '../ui/Button';
import { RiskBadge, ScanStatusBadge } from '../ui/StatusBadge';
import { DataTable } from '../ui/Table';
import styles from './Scans.module.css';
import { FileName } from '../ui/FileName';

export function RecentScansTable({ scans }: { scans: ScanListItem[] }) {
  return (
    <DataTable
      caption="Recent scans"
      rows={scans}
      getRowId={(scan) => scan.id}
      columns={[
        {
          id: 'document',
          header: 'Document',
          cell: (scan) => (
            <Link to={`/app/scans/${scan.id}`} className={styles.documentName}>
              <FileName name={scan.documentName} />
            </Link>
          ),
        },
        { id: 'status', header: 'Status', cell: (scan) => <ScanStatusBadge status={scan.status} />, nowrap: true },
        {
          id: 'findings',
          header: 'Findings',
          cell: (scan) => (scan.findingCount === null ? <span className="muted">—</span> : formatNumber(scan.findingCount)),
          align: 'right',
        },
        {
          id: 'risk',
          header: 'Risk',
          cell: (scan) => (scan.riskLevel ? <RiskBadge level={scan.riskLevel} /> : <span className="muted">—</span>),
          nowrap: true,
          hideBelow: 'mobile',
        },
        {
          id: 'scanned',
          header: 'Scanned',
          cell: (scan) => <span className="secondary">{formatRelativeTime(scan.createdAt)}</span>,
          nowrap: true,
          hideBelow: 'tablet',
        },
        {
          id: 'action',
          header: <span className="visually-hidden">Action</span>,
          cell: (scan) => (
            <ButtonLink to={`/app/scans/${scan.id}`} size="sm" variant="ghost" aria-label={`View scan of ${scan.documentName}`}>
              View
            </ButtonLink>
          ),
          align: 'right',
          hideBelow: 'mobile',
        },
      ]}
    />
  );
}
