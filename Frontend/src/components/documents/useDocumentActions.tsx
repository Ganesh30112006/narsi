import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useToast } from '../../hooks/useToast';
import { toApiError } from '../../services/apiError';
import { documentApi } from '../../services/documentApi';
import { scanApi } from '../../services/scanApi';
import type { DocumentRecord } from '../../types/document';
import { saveBlob } from '../../utils/file';
import { sanitizeFileName } from '../../utils/security';
import { ConfirmDialog } from '../ui/Dialog';

interface Options {
  onDeleted?(document: DocumentRecord): void;
}

/**
 * Shared document actions with the confirmations sensitive operations require.
 * Render `dialogs` once in the calling component.
 */
export function useDocumentActions({ onDeleted }: Options = {}) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const [pendingDelete, setPendingDelete] = useState<DocumentRecord | null>(null);
  const [pendingDownload, setPendingDownload] = useState<DocumentRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [scanningId, setScanningId] = useState<string | null>(null);

  const startScan = async (document: DocumentRecord) => {
    setScanningId(document.id);
    try {
      const scan = await scanApi.createScan({ documentId: document.id });
      notify({ tone: 'info', title: 'Scan started', description: document.fileName });
      navigate(`/app/scans/${scan.id}`);
    } catch (error) {
      const apiError = toApiError(error);
      if (apiError.kind === 'conflict' && document.latestScanId) {
        notify({ tone: 'info', title: 'A scan is already running', description: 'Showing its progress.' });
        navigate(`/app/scans/${document.latestScanId}`);
      } else {
        notify({ tone: 'error', title: 'Unable to start scan', description: apiError.message });
      }
    } finally {
      setScanningId(null);
    }
  };

  const performDownload = async (document: DocumentRecord) => {
    setDownloading(true);
    try {
      const { blob, fileName } = await documentApi.download(document.id);
      saveBlob(blob, sanitizeFileName(fileName ?? document.fileName));
      notify({
        tone: 'success',
        title: document.variant === 'SANITIZED' ? 'Sanitized copy downloaded' : 'Document downloaded',
        description: document.fileName,
      });
      setPendingDownload(null);
    } catch (error) {
      setPendingDownload(null);
      notify({ tone: 'error', title: 'Download failed', description: toApiError(error).message });
    } finally {
      setDownloading(false);
    }
  };

  /** Sanitized copies download directly; originals may contain PII and require confirmation. */
  const download = (document: DocumentRecord) => {
    if (document.variant === 'SANITIZED') void performDownload(document);
    else setPendingDownload(document);
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await documentApi.remove(pendingDelete.id);
      notify({ tone: 'success', title: 'Document deleted', description: pendingDelete.fileName });
      onDeleted?.(pendingDelete);
      setPendingDelete(null);
    } catch (error) {
      notify({ tone: 'error', title: 'Unable to delete document', description: toApiError(error).message });
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  };

  const dialogs = (
    <>
      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this document?"
        description={
          <>
            <strong>{pendingDelete?.fileName}</strong> and its scan results will be permanently deleted. This can't be undone.
          </>
        }
        confirmLabel="Delete document"
        tone="danger"
        loading={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
      <ConfirmDialog
        open={Boolean(pendingDownload)}
        title="Download original document?"
        description={
          (pendingDownload?.findingCount ?? 0) > 0
            ? `This file contains ${pendingDownload?.findingCount} detected PII findings. Consider downloading a sanitized copy instead. The download is recorded in the audit log.`
            : 'The original file may contain sensitive information. The download is recorded in the audit log.'
        }
        confirmLabel="Download original"
        tone="warning"
        loading={downloading}
        onConfirm={() => pendingDownload && void performDownload(pendingDownload)}
        onCancel={() => setPendingDownload(null)}
      />
    </>
  );

  return { startScan, download, requestDelete: setPendingDelete, scanningId, dialogs };
}
