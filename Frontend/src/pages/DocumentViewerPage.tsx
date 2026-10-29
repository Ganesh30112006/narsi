import { useCallback, useMemo, useState } from 'react';
import { ChartNoAxesColumn, Download, Eraser, FileCheck, FileWarning, Info, ScanSearch } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useDocumentActions } from '../components/documents/useDocumentActions';
import { RedactionDialog } from '../components/redaction/RedactionDialog';
import { Badge } from '../components/ui/Badge';
import { Button, ButtonLink } from '../components/ui/Button';
import { ConfirmDialog } from '../components/ui/Dialog';
import { PageHeader } from '../components/ui/Layout';
import { SkeletonBlock } from '../components/ui/Skeleton';
import { EmptyState, ErrorState, InlineNotice } from '../components/ui/StateViews';
import { DocumentStatusBadge } from '../components/ui/StatusBadge';
import { FindingPanel } from '../components/viewer/FindingPanel';
import type { Rotation } from '../components/viewer/PageCanvas';
import { PageCanvas } from '../components/viewer/PageCanvas';
import { ViewerToolbar } from '../components/viewer/ViewerToolbar';
import viewerStyles from '../components/viewer/Viewer.module.css';
import { useAuth } from '../hooks/useAuth';
import { useDocument } from '../hooks/useDocuments';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useFindings } from '../hooks/useFindings';
import { useResource } from '../hooks/useResource';
import { documentApi } from '../services/documentApi';
import type { Finding } from '../types/finding';
import { formatBytes, formatDate, pluralize } from '../utils/formatting';
import styles from './Pages.module.css';
import { FileName } from '../components/ui/FileName';

export default function DocumentViewerPage() {
  const { documentId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const document = useDocument(documentId);
  const doc = document.data;
  useDocumentTitle(doc?.fileName ?? 'Document');

  const pages = useResource(`pages:${documentId}`, (signal) => documentApi.listPages(documentId, signal), {
    enabled: Boolean(documentId),
  });
  const scanned = doc?.variant === 'ORIGINAL' && doc.scanStatus === 'COMPLETED' && Boolean(doc.latestScanId);
  const findings = useFindings(
    { documentId, scanId: doc?.latestScanId ?? undefined, pageSize: 100, sortBy: 'page', sortOrder: 'asc' },
    { enabled: scanned },
  );
  const actions = useDocumentActions();

  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState<Rotation>(0);
  const canSeeValues = can('pii:reveal');
  const [obscure, setObscure] = useState(true);
  const [confirmUncover, setConfirmUncover] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [redactOpen, setRedactOpen] = useState(false);
  const selectedId = params.get('finding');

  const allFindings = useMemo(() => findings.data?.items ?? [], [findings.data]);
  const pageFindings = useMemo(
    () => allFindings.filter((finding) => finding.location.page === pageNumber),
    [allFindings, pageNumber],
  );

  // Deep link (?finding=) opens on that finding's page.
  const linked = allFindings.find((finding) => finding.id === selectedId);
  const [syncedLink, setSyncedLink] = useState<string | null>(null);
  if (linked && syncedLink !== linked.id) {
    setSyncedLink(linked.id);
    if (linked.location.page && linked.location.page !== pageNumber) setPageNumber(linked.location.page);
  }

  const select = useCallback(
    (finding: Finding, openPopover = true) => {
      if (finding.location.page) setPageNumber(finding.location.page);
      const next = new URLSearchParams(params);
      next.set('finding', finding.id);
      setParams(next, { replace: true });
      setSyncedLink(finding.id);
      setPopoverOpen(openPopover);
    },
    [params, setParams],
  );

  if (document.status === 'error' && document.error) {
    return (
      <>
        <PageHeader title="Document" back={{ to: '/app/documents', label: 'Documents' }} />
        <ErrorState error={document.error} subject="this document" onRetry={document.reload} />
      </>
    );
  }

  if (!doc) {
    return (
      <>
        <PageHeader title="Loading document…" back={{ to: '/app/documents', label: 'Documents' }} />
        <SkeletonBlock lines={8} label="Loading document" />
      </>
    );
  }

  const pageList = pages.data ?? [];
  const currentPage = pageList.find((page) => page.pageNumber === pageNumber) ?? pageList[0];
  const pageCount = pageList.length;
  const sanitized = doc.variant === 'SANITIZED';
  const effectiveObscure = !canSeeValues || obscure;
  const canRedact = can('redactions:create') && scanned && allFindings.length > 0;

  const headerActions = (
    <>
      {can('documents:download') && (
        <Button icon={<Download size={16} aria-hidden />} onClick={() => actions.download(doc)}>
          {sanitized ? 'Download sanitized copy' : 'Download'}
        </Button>
      )}
      {scanned && doc.latestScanId && (
        <ButtonLink to={`/app/scans/${doc.latestScanId}`} variant="secondary" icon={<ChartNoAxesColumn size={16} aria-hidden />}>
          Scan details
        </ButtonLink>
      )}
      {canRedact && (
        <Button variant="primary" icon={<Eraser size={16} aria-hidden />} onClick={() => setRedactOpen(true)}>
          Redact sensitive data
        </Button>
      )}
    </>
  );

  return (
    <>
      <PageHeader
        title={<FileName name={doc.fileName} />}
        back={{ to: '/app/documents', label: 'Documents' }}
        meta={
          <>
            {sanitized ? (
              <Badge tone="success" icon={<FileCheck size={12} aria-hidden />}>
                Sanitized copy
              </Badge>
            ) : (
              <Badge tone="outline">Original document</Badge>
            )}
            {!sanitized && <DocumentStatusBadge status={doc.scanStatus} />}
            <span>{doc.fileType}</span>
            <span>{formatBytes(doc.sizeBytes)}</span>
            <span>Uploaded {formatDate(doc.uploadedAt)}</span>
            {scanned && <span>{pluralize(allFindings.length, 'finding')}</span>}
          </>
        }
        actions={headerActions}
      />

      {sanitized && (
        <div className={styles.gapBelow}>
          <InlineNotice tone="success">
            <Info size={16} aria-hidden />
            <span>
              Redacted values have been permanently removed from this copy.{' '}
              {doc.sourceDocumentId && <Link to={`/app/documents/${doc.sourceDocumentId}`}>View original document</Link>}
            </span>
          </InlineNotice>
        </div>
      )}

      {!sanitized && doc.scanStatus !== 'COMPLETED' && (
        <div className={styles.gapBelow}>
          <InlineNotice
            tone={doc.scanStatus === 'FAILED' ? 'danger' : 'info'}
            action={
              doc.scanStatus === 'QUEUED' || doc.scanStatus === 'PROCESSING'
                ? doc.latestScanId && (
                    <ButtonLink to={`/app/scans/${doc.latestScanId}`} size="sm">
                      View progress
                    </ButtonLink>
                  )
                : can('scans:create') && (
                    <Button
                      size="sm"
                      icon={<ScanSearch size={14} aria-hidden />}
                      loading={actions.scanningId === doc.id}
                      onClick={() => void actions.startScan(doc)}
                    >
                      {doc.scanStatus === 'FAILED' ? 'Scan again' : 'Scan document'}
                    </Button>
                  )
            }
          >
            <FileWarning size={16} aria-hidden />
            <span>
              {doc.scanStatus === 'FAILED'
                ? 'The last scan of this document failed. No findings are available.'
                : doc.scanStatus === 'NOT_SCANNED'
                  ? "This document hasn't been scanned yet."
                  : 'A scan is in progress. Findings will appear when it completes.'}
            </span>
          </InlineNotice>
        </div>
      )}

      {pages.status === 'error' && pages.error ? (
        <ErrorState error={pages.error} subject="the document preview" onRetry={pages.reload} />
      ) : pages.data && pageCount === 0 ? (
        <EmptyState title="Preview unavailable" description="This document has no renderable pages. You can still download it." />
      ) : (
        <div className={[viewerStyles.viewer, !scanned && viewerStyles.viewerSingle].filter(Boolean).join(' ')}>
          <div className={viewerStyles.canvasColumn}>
            <ViewerToolbar
              page={pageNumber}
              pageCount={Math.max(pageCount, 1)}
              onPageChange={(page) => {
                setPageNumber(page);
                setPopoverOpen(false);
              }}
              zoom={zoom}
              onZoomChange={setZoom}
              onRotate={() => setRotation((current) => ((current + 90) % 360) as Rotation)}
              obscure={effectiveObscure}
              onToggleObscure={canSeeValues && scanned ? () => (obscure ? setConfirmUncover(true) : setObscure(true)) : undefined}
            />
            <div className={viewerStyles.scroll}>
              {currentPage ? (
                <PageCanvas
                  documentId={doc.id}
                  page={currentPage}
                  findings={pageFindings}
                  zoom={zoom}
                  rotation={rotation}
                  obscure={effectiveObscure}
                  selectedId={selectedId}
                  popoverOpen={popoverOpen}
                  onSelect={(finding) => select(finding)}
                  onClosePopover={() => setPopoverOpen(false)}
                />
              ) : (
                <div className={viewerStyles.surface}>
                  <SkeletonBlock lines={10} label="Loading pages" />
                </div>
              )}
            </div>
          </div>

          {scanned &&
            (findings.status === 'error' && findings.error ? (
              <div className={viewerStyles.panel}>
                <ErrorState error={findings.error} subject="findings" onRetry={findings.reload} compact />
              </div>
            ) : findings.data ? (
              allFindings.length > 0 ? (
                <FindingPanel
                  findings={allFindings}
                  selectedId={selectedId}
                  currentPage={pageNumber}
                  onSelect={(finding) => select(finding, false)}
                />
              ) : (
                <div className={viewerStyles.panel}>
                  <p className={viewerStyles.panelEmpty}>No PII was detected in this document.</p>
                </div>
              )
            ) : (
              <div className={viewerStyles.panel}>
                <div className={viewerStyles.panelEmpty}>
                  <SkeletonBlock lines={6} label="Loading findings" />
                </div>
              </div>
            ))}
        </div>
      )}

      <ConfirmDialog
        open={confirmUncover}
        title="Show detected values on the page?"
        description="Sensitive values will be readable in the document preview. Make sure no one else can see your screen."
        confirmLabel="Show values"
        tone="warning"
        onConfirm={() => {
          setObscure(false);
          setConfirmUncover(false);
        }}
        onCancel={() => setConfirmUncover(false)}
      />

      {redactOpen && canRedact && doc.latestScanId && (
        <RedactionDialog
          onClose={() => setRedactOpen(false)}
          documentId={doc.id}
          documentName={doc.fileName}
          scanId={doc.latestScanId}
          findings={allFindings}
          onCompleted={() => findings.reload()}
        />
      )}
      {actions.dialogs}
    </>
  );
}
