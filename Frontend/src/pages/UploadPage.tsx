import { useCallback, useEffect, useRef, useState } from 'react';
import { Info } from 'lucide-react';
import { FileDropzone } from '../components/documents/FileDropzone';
import type { UploadEntry } from '../components/documents/UploadQueue';
import { UploadQueue } from '../components/documents/UploadQueue';
import { Button, ButtonLink } from '../components/ui/Button';
import { Checkbox } from '../components/ui/Field';
import { PageHeader, Section } from '../components/ui/Layout';
import { InlineNotice } from '../components/ui/StateViews';
import { usePermission } from '../hooks/useAuth';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useToast } from '../hooks/useToast';
import { toApiError } from '../services/apiError';
import { documentApi } from '../services/documentApi';
import { scanApi } from '../services/scanApi';
import { validateFile } from '../utils/file';
import { pluralize } from '../utils/formatting';
import styles from './UploadPage.module.css';

const MAX_FILES = 20;

function uploadErrorMessage(error: unknown): string {
  const apiError = toApiError(error);
  switch (apiError.kind) {
    case 'payload_too_large':
      return 'This file is larger than the server allows.';
    case 'validation':
      return apiError.fieldErrors.file ?? apiError.message;
    case 'network':
    case 'timeout':
      return 'Upload interrupted. Check your connection and retry.';
    case 'forbidden':
      return "You don't have permission to upload documents.";
    default:
      return "We couldn't upload this file. Please try again.";
  }
}

export default function UploadPage() {
  useDocumentTitle('Upload documents');
  const canScan = usePermission('scans:create');
  const { notify } = useToast();
  const [entries, setEntries] = useState<UploadEntry[]>([]);
  const [autoScan, setAutoScan] = useState(canScan);
  const [running, setRunning] = useState(false);
  const controllers = useRef(new Map<string, AbortController>());
  const counter = useRef(0);

  const update = useCallback((id: string, changes: Partial<UploadEntry>) => {
    setEntries((current) => current.map((entry) => (entry.id === id ? { ...entry, ...changes } : entry)));
  }, []);

  // Abort in-flight uploads when leaving the page.
  useEffect(() => {
    const active = controllers.current;
    return () => active.forEach((controller) => controller.abort());
  }, []);

  const addFiles = (files: File[]) => {
    const room = MAX_FILES - entries.length;
    if (files.length > room) {
      notify({ tone: 'warning', title: `You can add up to ${MAX_FILES} files at a time` });
    }
    const accepted = files.slice(0, Math.max(0, room)).map<UploadEntry>((file) => {
      counter.current += 1;
      return {
        id: `upload-${counter.current}`,
        file,
        fileType: null,
        status: 'validating',
        progress: 0,
        error: null,
        document: null,
        scanId: null,
      };
    });
    setEntries((current) => [...current, ...accepted]);
    accepted.forEach((entry) => {
      void validateFile(entry.file).then((result) =>
        update(
          entry.id,
          result.ok ? { status: 'ready', fileType: result.fileType } : { status: 'invalid', error: result.reason },
        ),
      );
    });
  };

  const uploadOne = async (entry: UploadEntry): Promise<boolean> => {
    const controller = new AbortController();
    controllers.current.set(entry.id, controller);
    update(entry.id, { status: 'uploading', progress: 0, error: null });
    try {
      const document = await documentApi.upload(entry.file, {
        signal: controller.signal,
        onProgress: (fraction) => update(entry.id, { progress: fraction }),
      });
      if (autoScan && canScan) {
        update(entry.id, { status: 'starting-scan', document, progress: 1 });
        try {
          const scan = await scanApi.createScan({ documentId: document.id });
          update(entry.id, { status: 'done', scanId: scan.id });
        } catch {
          update(entry.id, { status: 'done' });
          notify({ tone: 'warning', title: 'Uploaded, but the scan could not start', description: entry.file.name });
        }
      } else {
        update(entry.id, { status: 'done', document, progress: 1 });
      }
      return true;
    } catch (error) {
      const apiError = toApiError(error);
      update(entry.id, {
        status: 'failed',
        error: apiError.kind === 'cancelled' ? 'Upload cancelled.' : uploadErrorMessage(error),
      });
      return false;
    } finally {
      controllers.current.delete(entry.id);
    }
  };

  const uploadReady = async () => {
    const ready = entries.filter((entry) => entry.status === 'ready');
    if (ready.length === 0) return;
    setRunning(true);
    let succeeded = 0;
    // Sequential uploads keep bandwidth predictable for large documents.
    for (const entry of ready) {
      if (await uploadOne(entry)) succeeded += 1;
    }
    setRunning(false);
    if (succeeded > 0) {
      notify({
        tone: 'success',
        title: succeeded === 1 ? 'Document uploaded successfully' : `${succeeded} documents uploaded successfully`,
        description: autoScan && canScan ? 'Scanning has started.' : undefined,
      });
    }
    if (succeeded < ready.length) {
      notify({ tone: 'error', title: 'Some files could not be uploaded', description: 'Review the list and retry.' });
    }
  };

  const readyCount = entries.filter((entry) => entry.status === 'ready').length;
  const validating = entries.some((entry) => entry.status === 'validating');
  const finished = entries.filter((entry) => entry.status === 'done');

  return (
    <>
      <PageHeader
        title="Upload documents"
        description="Files are checked in your browser before upload, then scanned for government-issued PII."
        back={{ to: '/app/documents', label: 'Documents' }}
      />

      <FileDropzone onFiles={addFiles} disabled={running} />

      {entries.length > 0 && (
        <div className={styles.queue}>
          <Section
            title="Selected files"
            description={pluralize(entries.length, 'file')}
            id="upload-queue"
            actions={
              !running &&
              entries.some((entry) => entry.status !== 'done') && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEntries((current) => current.filter((entry) => entry.status === 'done'))}
                >
                  Clear pending
                </Button>
              )
            }
          >
            <UploadQueue
              entries={entries}
              onRemove={(id) => setEntries((current) => current.filter((entry) => entry.id !== id))}
              onCancel={(id) => controllers.current.get(id)?.abort()}
              onRetry={(id) => {
                const entry = entries.find((candidate) => candidate.id === id);
                if (entry) void uploadOne(entry);
              }}
            />

            <div className={styles.footer}>
              {canScan ? (
                <Checkbox
                  label="Start scanning after upload"
                  description="Uses your default scan preferences."
                  checked={autoScan}
                  onChange={(event) => setAutoScan(event.target.checked)}
                  disabled={running}
                />
              ) : (
                <span />
              )}
              <div className={styles.footerActions}>
                {finished.length > 0 && !running && (
                  <ButtonLink to="/app/documents" variant="secondary">
                    Go to documents
                  </ButtonLink>
                )}
                <Button
                  variant="primary"
                  onClick={() => void uploadReady()}
                  disabled={readyCount === 0 || validating}
                  loading={running}
                  loadingLabel="Uploading"
                >
                  {readyCount > 1 ? `Upload ${readyCount} files` : 'Upload'}
                </Button>
              </div>
            </div>
          </Section>
        </div>
      )}

      {entries.length === 0 && (
        <div className={styles.note}>
          <InlineNotice tone="info">
            <Info size={16} aria-hidden />
            <span>Uploaded originals are never modified. Redaction always produces a separate sanitized copy.</span>
          </InlineNotice>
        </div>
      )}
    </>
  );
}
