import { Link } from 'react-router';
import type { Finding } from '../../types/finding';
import { detectedBy } from '../../utils/findings';
import { formatDateTime } from '../../utils/formatting';
import { DETECTION_METHOD_LABELS } from '../../utils/labels';
import type { Column, SortState } from '../ui/Table';
import { DataTable } from '../ui/Table';
import { ValidationBadge } from '../ui/StatusBadge';
import { ConfidenceIndicator } from './ConfidenceIndicator';
import { FindingBadge } from './FindingBadge';
import styles from './Findings.module.css';
import { FileName } from '../ui/FileName';

type FindingColumn = 'type' | 'value' | 'document' | 'confidence' | 'page' | 'method' | 'status' | 'created';

interface FindingsTableProps {
  findings: Finding[] | undefined;
  loading?: boolean;
  refreshing?: boolean;
  columns?: FindingColumn[];
  sort?: SortState;
  onSortChange?(sort: SortState): void;
  onSelect?(finding: Finding): void;
  selectedId?: string | null;
  caption?: string;
}

const ALL_COLUMNS: Record<FindingColumn, Column<Finding>> = {
  type: {
    id: 'type',
    header: 'PII type',
    cell: (finding) => <FindingBadge type={finding.piiType} />,
    sortKey: 'piiType',
    nowrap: true,
  },
  value: {
    id: 'value',
    header: 'Value',
    cell: (finding) => <code className={styles.tableValue}>{finding.maskedValue}</code>,
    hideBelow: 'mobile',
  },
  document: {
    id: 'document',
    header: 'Document',
    cell: (finding) => (
      <Link to={`/app/documents/${finding.documentId}?finding=${finding.id}`} className={styles.documentLink}>
        <FileName name={finding.documentName} />
      </Link>
    ),
  },
  confidence: {
    id: 'confidence',
    header: 'Confidence',
    cell: (finding) => <ConfidenceIndicator confidence={finding.confidence} level={finding.confidenceLevel} />,
    sortKey: 'confidence',
    nowrap: true,
  },
  page: {
    id: 'page',
    header: 'Page',
    cell: (finding) => (finding.location.page !== null ? finding.location.page : '—'),
    sortKey: 'page',
    align: 'right',
  },
  method: {
    id: 'method',
    header: 'Method',
    cell: (finding) => <span title={detectedBy(finding)}>{DETECTION_METHOD_LABELS[finding.detectionMethod]}</span>,
    nowrap: true,
    hideBelow: 'tablet',
  },
  status: {
    id: 'status',
    header: 'Status',
    cell: (finding) => <ValidationBadge status={finding.validationStatus} />,
    nowrap: true,
  },
  created: {
    id: 'created',
    header: 'Created',
    cell: (finding) => <span className="secondary">{formatDateTime(finding.createdAt)}</span>,
    sortKey: 'createdAt',
    nowrap: true,
    hideBelow: 'tablet',
  },
};

export function FindingsTable({
  findings,
  loading,
  refreshing,
  columns = ['type', 'document', 'confidence', 'page', 'method', 'status', 'created'],
  sort,
  onSortChange,
  onSelect,
  selectedId,
  caption = 'Findings',
}: FindingsTableProps) {
  return (
    <DataTable
      caption={caption}
      columns={columns.map((column) => ALL_COLUMNS[column])}
      rows={findings}
      getRowId={(finding) => finding.id}
      loading={loading}
      refreshing={refreshing}
      sort={sort}
      onSortChange={onSortChange}
      onRowClick={onSelect}
      selectedId={selectedId}
    />
  );
}
