import { useState } from 'react';
import { ChartNoAxesColumn, CircleAlert, Eraser, FileSearch, RotateCw, ShieldCheck, TriangleAlert, WifiOff } from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import { ConfidenceSummary } from '../components/findings/ConfidenceSummary';
import { FindingDrawer } from '../components/findings/FindingDrawer';
import { FindingsTable } from '../components/findings/FindingsTable';
import { RedactionDialog } from '../components/redaction/RedactionDialog';
import { ScanTimeline } from '../components/scans/ScanTimeline';
import { Button, ButtonLink } from '../components/ui/Button';
import { DescriptionList, PageHeader, Section } from '../components/ui/Layout';
import { SkeletonBlock } from '../components/ui/Skeleton';
import { EmptyState, ErrorState, InlineNotice } from '../components/ui/StateViews';
import { ScanStatusBadge } from '../components/ui/StatusBadge';
import { useAuth } from '../hooks/useAuth';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useFindings } from '../hooks/useFindings';
import { useScan } from '../hooks/useScan';
import { useToast } from '../hooks/useToast';
import { toApiError } from '../services/apiError';
import { scanApi } from '../services/scanApi';
import type { Finding } from '../types/finding';
import type { Scan } from '../types/scan';
import { formatDateTime, pluralize } from '../utils/formatting';
import styles from './Pages.module.css';

function durationText(scan: Scan): string {
  if (!scan.startedAt || !scan.completedAt) return '—';
  const seconds = Math.max(0, Math.round((new Date(scan.completedAt).getTime() - new Date(scan.startedAt).getTime()) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export default function ScanDetailsPage() {
  const { scanId } = useParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const { scan, status, error, pollError, isActive, reload } = useScan(scanId);
  const completed = scan?.status === 'COMPLETED';
  const findings = useFindings(
    { scanId, pageSize: 100, sortBy: 'page', sortOrder: 'asc' },
    { enabled: Boolean(scanId && completed) },
  );
  const [selected, setSelected] = useState<Finding | null>(null);
  const [retrying, setRetrying] = useState(false);
  const redactOpen = params.get('redact') === '1';

  useDocumentTitle(scan ? `Scan · ${scan.documentName}` : 'Scan');

  const setRedactOpen = (open: boolean) => {
    const next = new URLSearchParams(params);
    if (open) next.set('redact', '1');
    else next.delete('redact');
    setParams(next, { replace: true });
  };

  const retry = async () => {
    if (!scan) return;
    setRetrying(true);
    try {
      const next = await scanApi.retryScan(scan.id);
      if (next.id === scan.id) reload();
      else navigate(`/app/scans/${next.id}`, { replace: true });
    } catch (caught) {
      notify({ tone: 'error', title: 'Unable to restart scan', description: toApiError(caught).message });
    } finally {
      setRetrying(false);
    }
  };

  if (status === 'error' && error) {
    return (
      <>
        <PageHeader title="Scan" back={{ to: '/app/documents', label: 'Documents' }} />
        <ErrorState error={error} subject="this scan" onRetry={reload} />
      </>
    );
  }

  if (!scan) {
    return (
      <>
        <PageHeader title="Loading scan…" back={{ to: '/app/documents', label: 'Documents' }} />
        <SkeletonBlock lines={6} label="Loading scan" />
      </>
    );
  }

  const findingCount = scan.findingCount ?? 0;
  const canRedact = can('redactions:create') && completed && findingCount > 0;

  const title = isActive
    ? 'Scanning document'
    : scan.status === 'FAILED'
      ? 'Scan failed'
      : scan.status === 'COMPLETED'
        ? 'Scan completed'
        : 'Scan';
  const outcome = completed
    ? findingCount > 0
      ? `${pluralize(findingCount, 'PII finding')} detected`
      : 'No PII detected'
    : null;

  const actions = completed && (
    <>
      <ButtonLink to={`/app/documents/${scan.documentId}`} variant="secondary" icon={<FileSearch size={16} aria-hidden />}>
        Open document
      </ButtonLink>
      {scan.reportId && can('reports:read') && (
        <ButtonLink to={`/app/reports/${scan.reportId}`} variant="secondary" icon={<ChartNoAxesColumn size={16} aria-hidden />}>
          View report
        </ButtonLink>
      )}
      {canRedact && (
        <Button variant="primary" icon={<Eraser size={16} aria-hidden />} onClick={() => setRedactOpen(true)}>
          Redact sensitive data
        </Button>
      )}
    </>
  );

  const processingDetails = (
    <DescriptionList
      items={[
        { label: 'Status', value: <ScanStatusBadge status={scan.status} /> },
        { label: 'Scanner', value: <span className="mono">{scan.scannerVersion}</span> },
        { label: 'OCR', value: scan.ocrEnabled ? 'Used' : 'Not used' },
        { label: 'Started', value: formatDateTime(scan.startedAt) },
        { label: 'Completed', value: formatDateTime(scan.completedAt) },
        { label: 'Duration', value: durationText(scan) },
      ]}
    />
  );

  return (
    <>
      <PageHeader
        title={title}
        description={<span className={styles.metaStrong}>{scan.documentName}</span>}
        back={{ to: '/app/documents', label: 'Documents' }}
        meta={outcome && <span className={styles.outcome}>{outcome}</span>}
        actions={actions}
      />

      {scan.warnings && scan.warnings.length > 0 && (
        <div className={styles.gapBelow}>
          <InlineNotice tone="warning">
            <TriangleAlert size={16} aria-hidden />
            <span>{scan.warnings.join(' ')}</span>
          </InlineNotice>
        </div>
      )}

      {isActive && (
        <div className={styles.split}>
          <Section title="Progress" id="scan-progress">
            <div className={styles.sectionPad}>
              {pollError && (
                <div className={styles.gapBelow}>
                  <InlineNotice tone="warning">
                    <WifiOff size={16} aria-hidden />
                    Connection interrupted. Showing the last known status while we retry.
                  </InlineNotice>
                </div>
              )}
              <ScanTimeline stages={scan.stages} progress={scan.progress} />
            </div>
          </Section>
          <aside className={styles.aside}>
            <InlineNotice tone="info">
              <ShieldCheck size={16} aria-hidden />
              <span>
                You can leave this page. The scan continues in the background and appears in Recent scans on the dashboard.
              </span>
            </InlineNotice>
            {processingDetails}
          </aside>
        </div>
      )}

      {scan.status === 'FAILED' && (
        <div className={styles.split}>
          <Section title="What happened" id="scan-failure">
            <div className={styles.sectionPad}>
              <InlineNotice
                tone="danger"
                action={
                  scan.error?.retryable !== false &&
                  can('scans:create') && (
                    <Button size="sm" icon={<RotateCw size={14} aria-hidden />} loading={retrying} onClick={() => void retry()}>
                      Try again
                    </Button>
                  )
                }
              >
                <CircleAlert size={16} aria-hidden />
                <span>
                  <strong>We couldn't complete this scan.</strong> {scan.error?.message ?? 'An unexpected error occurred.'}
                </span>
              </InlineNotice>
              <div className={styles.gapAbove}>
                <ScanTimeline stages={scan.stages} progress={scan.progress} />
              </div>
            </div>
          </Section>
          <aside className={styles.aside}>{processingDetails}</aside>
        </div>
      )}

      {completed && (
        <div className={styles.split}>
          <Section
            title="Findings"
            id="scan-findings"
            description={findingCount > 0 ? 'Select a finding to see why it was flagged.' : undefined}
          >
            {findingCount === 0 ? (
              <EmptyState
                icon={ShieldCheck}
                title="No PII detected"
                description="The scanner did not find government-issued identifiers or personal data in this document."
                compact
              />
            ) : findings.status === 'error' && findings.error ? (
              <ErrorState error={findings.error} subject="findings" onRetry={findings.reload} compact />
            ) : (
              <FindingsTable
                caption={`Findings in ${scan.documentName}`}
                findings={findings.data?.items}
                loading={findings.status === 'loading'}
                columns={['type', 'value', 'confidence', 'page', 'method', 'status']}
                onSelect={setSelected}
                selectedId={selected?.id}
              />
            )}
          </Section>
          <aside className={styles.aside}>
            {scan.confidenceSummary && findingCount > 0 && (
              <Section title="Summary" id="scan-summary" description="Findings by confidence level">
                <div className={styles.sectionPad}>
                  <ConfidenceSummary summary={scan.confidenceSummary} />
                </div>
              </Section>
            )}
            <Section title="Processing" id="scan-processing" description="How this document was scanned">
              <div className={styles.sectionPad}>{processingDetails}</div>
            </Section>
          </aside>
        </div>
      )}

      <FindingDrawer finding={selected} onClose={() => setSelected(null)} />

      {redactOpen && canRedact && findings.data && (
        <RedactionDialog
          onClose={() => setRedactOpen(false)}
          documentId={scan.documentId}
          documentName={scan.documentName}
          scanId={scan.id}
          findings={findings.data.items}
          onCompleted={() => findings.reload()}
        />
      )}
    </>
  );
}
