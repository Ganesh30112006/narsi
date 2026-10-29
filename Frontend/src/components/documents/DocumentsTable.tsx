import { Download, Ellipsis, Eraser, Eye, ScanSearch, Trash2 } from 'lucide-react';
import { Link, useNavigate } from 'react-router';
import { useAuth } from '../../hooks/useAuth';
import type { DocumentRecord } from '../../types/document';
import { formatBytes, formatDate, formatNumber } from '../../utils/formatting';
import { Badge } from '../ui/Badge';
import { IconButton } from '../ui/Button';
import type { MenuItem } from '../ui/Menu';
import { Menu } from '../ui/Menu';
import { DocumentStatusBadge, RiskBadge } from '../ui/StatusBadge';
import type { SortState } from '../ui/Table';
import { DataTable } from '../ui/Table';
import { FileTypeIcon } from './FileTypeIcon';
import styles from './Documents.module.css';
import { FileName } from '../ui/FileName';

interface DocumentsTableProps {
  documents: DocumentRecord[] | undefined;
  loading?: boolean;
  refreshing?: boolean;
  sort: SortState;
  onSortChange(sort: SortState): void;
  onScan(document: DocumentRecord): void;
  onDownload(document: DocumentRecord): void;
  onDelete(document: DocumentRecord): void;
  scanningId?: string | null;
}

export function DocumentsTable({
  documents,
  loading,
  refreshing,
  sort,
  onSortChange,
  onScan,
  onDownload,
  onDelete,
  scanningId,
}: DocumentsTableProps) {
  const { can } = useAuth();
  const navigate = useNavigate();

  const actionsFor = (document: DocumentRecord): MenuItem[] => {
    const scanning = document.scanStatus === 'QUEUED' || document.scanStatus === 'PROCESSING';
    const items: MenuItem[] = [
      {
        id: 'view',
        label: 'View',
        icon: <Eye size={15} aria-hidden />,
        onSelect: () => navigate(`/app/documents/${document.id}`),
      },
    ];
    if (can('scans:create') && document.variant === 'ORIGINAL') {
      items.push({
        id: 'scan',
        label: scanning ? 'View scan progress' : document.scanStatus === 'NOT_SCANNED' ? 'Scan' : 'Scan again',
        icon: <ScanSearch size={15} aria-hidden />,
        disabled: scanningId === document.id,
        onSelect: () => (scanning && document.latestScanId ? navigate(`/app/scans/${document.latestScanId}`) : onScan(document)),
      });
    }
    if (can('documents:download')) {
      items.push({
        id: 'download',
        label: 'Download',
        icon: <Download size={15} aria-hidden />,
        onSelect: () => onDownload(document),
      });
    }
    if (
      can('redactions:create') &&
      document.variant === 'ORIGINAL' &&
      document.scanStatus === 'COMPLETED' &&
      (document.findingCount ?? 0) > 0
    ) {
      items.push({
        id: 'redact',
        label: 'Redact',
        icon: <Eraser size={15} aria-hidden />,
        onSelect: () => navigate(`/app/scans/${document.latestScanId}?redact=1`),
      });
    }
    if (can('documents:delete')) {
      items.push({
        id: 'delete',
        label: 'Delete',
        icon: <Trash2 size={15} aria-hidden />,
        onSelect: () => onDelete(document),
        danger: true,
        separated: true,
      });
    }
    return items;
  };

  return (
    <DataTable
      caption="Documents"
      rows={documents}
      getRowId={(document) => document.id}
      loading={loading}
      refreshing={refreshing}
      sort={sort}
      onSortChange={onSortChange}
      skeletonRows={8}
      columns={[
        {
          id: 'file',
          header: 'File',
          sortKey: 'fileName',
          cell: (document) => (
            <div className={styles.fileCell}>
              <FileTypeIcon type={document.fileType} />
              <div className={styles.fileText}>
                <Link to={`/app/documents/${document.id}`} className={styles.fileName}>
                  <FileName name={document.fileName} />
                </Link>
                <div className={styles.fileMeta}>
                  {document.variant === 'SANITIZED' ? (
                    <Badge tone="success">Sanitized copy</Badge>
                  ) : (
                    <span>by {document.uploadedBy.name}</span>
                  )}
                </div>
              </div>
            </div>
          ),
        },
        { id: 'type', header: 'Type', cell: (document) => document.fileType, hideBelow: 'mobile' },
        {
          id: 'size',
          header: 'Size',
          sortKey: 'sizeBytes',
          cell: (document) => <span className="tabular">{formatBytes(document.sizeBytes)}</span>,
          align: 'right',
          nowrap: true,
          hideBelow: 'tablet',
        },
        {
          id: 'status',
          header: 'Scan status',
          cell: (document) => <DocumentStatusBadge status={document.scanStatus} />,
          nowrap: true,
        },
        {
          id: 'findings',
          header: 'PII findings',
          sortKey: 'findingCount',
          cell: (document) =>
            document.findingCount === null ? (
              <span className="muted">—</span>
            ) : (
              <span className={styles.findingsCell}>
                <span className="tabular">{formatNumber(document.findingCount)}</span>
                {document.riskLevel && document.riskLevel !== 'NONE' && <RiskBadge level={document.riskLevel} />}
              </span>
            ),
          nowrap: true,
        },
        {
          id: 'uploaded',
          header: 'Uploaded',
          sortKey: 'uploadedAt',
          cell: (document) => <span className="secondary">{formatDate(document.uploadedAt)}</span>,
          nowrap: true,
          hideBelow: 'tablet',
        },
        {
          id: 'actions',
          header: <span className="visually-hidden">Actions</span>,
          align: 'right',
          width: 48,
          cell: (document) => (
            <Menu
              items={actionsFor(document)}
              trigger={(props) => (
                <IconButton label={`Actions for ${document.fileName}`} size="sm" {...props}>
                  <Ellipsis size={16} aria-hidden />
                </IconButton>
              )}
            />
          ),
        },
      ]}
    />
  );
}
