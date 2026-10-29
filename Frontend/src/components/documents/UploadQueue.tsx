import { CircleAlert, CircleCheck, FileWarning, RotateCw, X } from 'lucide-react';
import type { DocumentFileType, DocumentRecord } from '../../types/document';
import { formatBytes } from '../../utils/formatting';
import { getExtension } from '../../utils/file';
import { Button, ButtonLink, IconButton } from '../ui/Button';
import { ProgressBar } from '../ui/ProgressBar';
import { Spinner } from '../ui/Spinner';
import { FileTypeIcon } from './FileTypeIcon';
import styles from './Documents.module.css';

export type UploadStatus = 'validating' | 'invalid' | 'ready' | 'uploading' | 'starting-scan' | 'done' | 'failed';

export interface UploadEntry {
  id: string;
  file: File;
  fileType: DocumentFileType | null;
  status: UploadStatus;
  progress: number;
  error: string | null;
  document: DocumentRecord | null;
  scanId: string | null;
}

interface UploadQueueProps {
  entries: UploadEntry[];
  onRemove(id: string): void;
  onCancel(id: string): void;
  onRetry(id: string): void;
}

function StatusText({ entry }: { entry: UploadEntry }) {
  switch (entry.status) {
    case 'validating':
      return (
        <span className={styles.uploadStatus}>
          <Spinner size={12} /> Checking file…
        </span>
      );
    case 'invalid':
    case 'failed':
      return (
        <span className={[styles.uploadStatus, styles.uploadError].join(' ')}>
          <CircleAlert size={14} aria-hidden />
          {entry.error}
        </span>
      );
    case 'ready':
      return <span className={styles.uploadStatus}>Ready to upload</span>;
    case 'uploading':
      return <span className={styles.uploadStatus}>Uploading · {Math.round(entry.progress * 100)}%</span>;
    case 'starting-scan':
      return (
        <span className={styles.uploadStatus}>
          <Spinner size={12} /> Uploaded · starting scan…
        </span>
      );
    case 'done':
      return (
        <span className={[styles.uploadStatus, styles.uploadSuccess].join(' ')}>
          <CircleCheck size={14} aria-hidden />
          {entry.scanId ? 'Uploaded · scan started' : 'Uploaded'}
        </span>
      );
  }
}

export function UploadQueue({ entries, onRemove, onCancel, onRetry }: UploadQueueProps) {
  return (
    <ul className={styles.queue} aria-label="Files to upload">
      {entries.map((entry) => (
        <li key={entry.id} className={styles.queueItem} data-status={entry.status}>
          {entry.fileType ? (
            <FileTypeIcon type={entry.fileType} />
          ) : (
            <span
              className={[styles.fileIcon, entry.status === 'invalid' && styles.fileIconInvalid].filter(Boolean).join(' ')}
              aria-hidden
            >
              {entry.status === 'invalid' && <FileWarning size={16} strokeWidth={1.75} />}
            </span>
          )}
          <div className={styles.queueBody}>
            <div className={styles.queueHeader}>
              <span className={styles.queueName}>{entry.file.name}</span>
              <span className={styles.queueMeta}>
                {entry.fileType ?? (getExtension(entry.file.name).toUpperCase() || 'Unknown')} · {formatBytes(entry.file.size)}
              </span>
            </div>
            <div aria-live="polite">
              <StatusText entry={entry} />
            </div>
            {entry.status === 'uploading' && (
              <div className={styles.queueProgress}>
                <ProgressBar value={entry.progress} label={`Uploading ${entry.file.name}`} />
              </div>
            )}
          </div>
          <div className={styles.queueActions}>
            {entry.status === 'done' && entry.scanId && (
              <ButtonLink to={`/app/scans/${entry.scanId}`} size="sm" variant="secondary">
                View scan
              </ButtonLink>
            )}
            {entry.status === 'done' && !entry.scanId && entry.document && (
              <ButtonLink to={`/app/documents/${entry.document.id}`} size="sm" variant="secondary">
                View
              </ButtonLink>
            )}
            {entry.status === 'failed' && (
              <Button size="sm" variant="secondary" icon={<RotateCw size={14} aria-hidden />} onClick={() => onRetry(entry.id)}>
                Retry
              </Button>
            )}
            {entry.status === 'uploading' ? (
              <Button size="sm" variant="ghost" onClick={() => onCancel(entry.id)}>
                Cancel
              </Button>
            ) : (
              entry.status !== 'starting-scan' &&
              entry.status !== 'done' && (
                <IconButton label={`Remove ${entry.file.name}`} size="sm" onClick={() => onRemove(entry.id)}>
                  <X size={16} aria-hidden />
                </IconButton>
              )
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
