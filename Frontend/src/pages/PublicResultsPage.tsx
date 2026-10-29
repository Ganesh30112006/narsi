import { useCallback, useEffect, useMemo, useState } from 'react';
import { CircleAlert, Download, Eraser, FileSearch, RotateCw, ShieldCheck, Trash2, TriangleAlert, WifiOff } from 'lucide-react';
import { useNavigate, useParams } from 'react-router';
import { ConfidenceIndicator } from '../components/findings/ConfidenceIndicator';
import { FindingBadge } from '../components/findings/FindingBadge';
import { FindingExplanation } from '../components/findings/FindingExplanation';
import { PublicLayout } from '../components/layout/PublicLayout';
import { IdChecks } from '../components/public/IdChecks';
import type { BadgeTone } from '../components/ui/Badge';
import { Badge } from '../components/ui/Badge';
import { ScanTimeline } from '../components/scans/ScanTimeline';
import { Button, ButtonLink } from '../components/ui/Button';
import { ConfirmDialog } from '../components/ui/Dialog';
import { Drawer } from '../components/ui/Drawer';
import { PageHeader, Section, StatCard, StatGroup } from '../components/ui/Layout';
import { SegmentedControl } from '../components/ui/SegmentedControl';
import { SkeletonBlock } from '../components/ui/Skeleton';
import { EmptyState, ErrorState, InlineNotice } from '../components/ui/StateViews';
import type { Column } from '../components/ui/Table';
import { DataTable } from '../components/ui/Table';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useToast } from '../hooks/useToast';
import type { ApiError } from '../services/apiError';
import { toApiError } from '../services/apiError';
import { publicApi } from '../services/publicApi';
import type { PIIType } from '../types/finding';
import type { PublicRedactionAction, PublicResult } from '../types/public';
import type { ReportExportFormat } from '../types/report';
import type { ScanStatusSnapshot } from '../types/scan';
import { saveBlob } from '../utils/file';
import { formatDateTime, pluralize } from '../utils/formatting';
import { forgetAccess, loadAccess } from '../utils/publicAccess';
import type { IdVerdict, ResultItem } from '../utils/publicResults';
import {
  describeWhere,
  documentTypeText,
  groupFindings,
  idVerdict,
  isIdType,
  isVisualType,
  signatureTitle,
  unreadablePageText,
  verificationText,
} from '../utils/publicResults';
import { sanitizeFileName } from '../utils/security';
import styles from './PublicPages.module.css';

const POLL_MS = 1200;
const REPORT_FORMATS: { format: ReportExportFormat; label: string }[] = [
  { format: 'pdf', label: 'PDF' },
  { format: 'csv', label: 'CSV' },
  { format: 'json', label: 'JSON' },
];

function isTerminal(status: ScanStatusSnapshot['status']) {
  return status === 'COMPLETED' || status === 'FAILED' || status === 'CANCELLED';
}

function countsByType(items: ResultItem[]): [PIIType, number][] {
  const counts = new Map<PIIType, number>();
  items.forEach((item) => counts.set(item.piiType, (counts.get(item.piiType) ?? 0) + 1));
  return [...counts.entries()];
}

const CHECK_BADGE: Record<IdVerdict, { tone: BadgeTone; label: string }> = {
  valid: { tone: 'success', label: 'Valid' },
  invalid: { tone: 'danger', label: 'Invalid' },
  unchecked: { tone: 'neutral', label: 'Not checked' },
};

const ITEM_COLUMNS: Column<ResultItem>[] = [
  { id: 'type', header: 'Kind of data', cell: (item) => <FindingBadge type={item.piiType} />, nowrap: true },
  {
    id: 'value',
    header: 'Value (masked)',
    cell: (item) => <code className={styles.maskedValue}>{item.maskedValue}</code>,
    hideBelow: 'mobile',
  },
  {
    id: 'check',
    header: 'ID check',
    cell: (item) => {
      if (!isIdType(item.piiType)) return <span className={styles.muted}>—</span>;
      const badge = CHECK_BADGE[idVerdict(item)];
      return <Badge tone={badge.tone}>{badge.label}</Badge>;
    },
    nowrap: true,
  },
  { id: 'where', header: 'Where', cell: (item) => describeWhere(item), nowrap: true, hideBelow: 'tablet' },
  {
    id: 'confidence',
    header: 'Confidence',
    cell: (item) => <ConfidenceIndicator confidence={item.best.confidence} level={item.best.confidenceLevel} />,
    nowrap: true,
  },
];

export default function PublicResultsPage() {
  const { scanId = '' } = useParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const access = useMemo(() => loadAccess(scanId), [scanId]);
  useDocumentTitle(access ? `Results · ${access.documentName}` : 'Results');

  const [status, setStatus] = useState<ScanStatusSnapshot | null>(null);
  const [result, setResult] = useState<PublicResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<ResultItem | null>(null);
  const [mode, setMode] = useState<PublicRedactionAction>('REDACT');
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const fail = useCallback(
    (caught: unknown) => {
      const apiError = toApiError(caught);
      if (apiError.kind === 'cancelled') return;
      if (apiError.kind === 'not_found') forgetAccess(scanId);
      if (apiError.kind === 'network' || apiError.kind === 'timeout') {
        setConnectionLost(true);
        return;
      }
      setError(apiError);
    },
    [scanId],
  );

  // Follow the scan until it finishes, then load the results.
  useEffect(() => {
    if (!access) return;
    const controller = new AbortController();
    let timer = 0;
    const tick = async () => {
      try {
        const snapshot = await publicApi.getStatus(scanId, access.token, controller.signal);
        setStatus(snapshot);
        setConnectionLost(false);
        if (isTerminal(snapshot.status)) {
          setResult(await publicApi.getResult(scanId, access.token, controller.signal));
          return;
        }
      } catch (caught) {
        fail(caught);
        if (toApiError(caught).kind !== 'network' && toApiError(caught).kind !== 'timeout') return;
      }
      timer = window.setTimeout(() => void tick(), POLL_MS);
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [access, scanId, attempt, fail]);

  // While a redacted copy is being made, refresh until it is ready (or has failed).
  const redactionPending = result?.redaction?.status === 'PROCESSING';
  useEffect(() => {
    if (!access || !redactionPending) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      publicApi.getResult(scanId, access.token, controller.signal).then(setResult).catch(fail);
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [access, scanId, redactionPending, result, fail]);

  if (!access) {
    return (
      <PublicLayout>
        <EmptyState
          icon={FileSearch}
          title="These results aren't available here"
          description="Results can only be opened in the browser tab that uploaded the file, and they are deleted after 24 hours."
          action={
            <ButtonLink to="/" variant="primary">
              Scan a file
            </ButtonLink>
          }
        />
      </PublicLayout>
    );
  }

  const run = async (label: string, action: () => Promise<void>) => {
    setBusy(label);
    try {
      await action();
    } catch (caught) {
      notify({ tone: 'error', title: "That didn't work", description: toApiError(caught).message });
    } finally {
      setBusy(null);
    }
  };

  const createRedaction = () =>
    run('redact', async () => {
      const redaction = await publicApi.createRedaction(scanId, access.token, mode);
      setResult((current) => (current ? { ...current, redaction } : current));
    });

  const downloadRedaction = () =>
    run('download', async () => {
      const { blob, fileName } = await publicApi.downloadRedaction(scanId, access.token);
      saveBlob(blob, sanitizeFileName(fileName ?? result?.redaction?.sanitizedFileName ?? 'redacted-document'));
    });

  const downloadReport = (format: ReportExportFormat) =>
    run(`report-${format}`, async () => {
      const { blob, fileName } = await publicApi.downloadReport(scanId, access.token, format);
      saveBlob(blob, sanitizeFileName(fileName ?? `report.${format}`));
    });

  const deleteUpload = () =>
    run('delete', async () => {
      await publicApi.remove(scanId, access.token);
      forgetAccess(scanId);
      notify({ tone: 'success', title: 'Deleted', description: `${access.documentName} and its results were deleted.` });
      navigate('/', { replace: true });
    });

  if (error) {
    return (
      <PublicLayout>
        {error.kind === 'not_found' ? (
          <EmptyState
            icon={FileSearch}
            title="These results are no longer available"
            description="The file and its results were deleted — either on request or automatically after 24 hours."
            action={
              <ButtonLink to="/" variant="primary">
                Scan a file
              </ButtonLink>
            }
          />
        ) : (
          <ErrorState
            error={error}
            subject="your results"
            onRetry={() => {
              setError(null);
              setAttempt((value) => value + 1);
            }}
          />
        )}
      </PublicLayout>
    );
  }

  const scan = result?.scan;
  const findings = result?.findings ?? [];
  const items = groupFindings(findings);
  const idItems = items.filter((item) => isIdType(item.piiType));
  const hasVisual = items.some((item) => isVisualType(item.piiType));
  const completed = scan?.status === 'COMPLETED';
  const failed = status?.status === 'FAILED' || scan?.status === 'FAILED';
  const redaction = result?.redaction ?? null;
  // Pages too blurred, dark or grainy to read: finding nothing there means "could not tell", never "clean".
  const unreadablePages = scan?.unreadablePages ?? [];
  const unreadable = unreadablePages.length > 0;
  const title = failed
    ? "We couldn't check this file"
    : completed
      ? items.length > 0
        ? `${pluralize(items.length, 'item')} of personal data found`
        : unreadable
          ? "We couldn't read this file clearly"
          : 'No personal data found'
      : 'Checking your file';

  return (
    <PublicLayout>
      <PageHeader
        title={title}
        description={
          <span className={styles.fileName}>
            {access.documentName}
            {documentTypeText(result?.documentType) && (
              <span className={styles.hint}> · {documentTypeText(result?.documentType)}</span>
            )}
          </span>
        }
        back={{ to: '/', label: 'Scan another file' }}
        actions={
          <Button
            variant="dangerOutline"
            icon={<Trash2 size={16} aria-hidden />}
            onClick={() => setConfirmDelete(true)}
            disabled={!result && !failed}
          >
            Delete my file now
          </Button>
        }
      />

      {connectionLost && (
        <div className={styles.gapBelow}>
          <InlineNotice tone="warning">
            <WifiOff size={16} aria-hidden />
            Connection interrupted. Showing the last known status while we retry.
          </InlineNotice>
        </div>
      )}

      {!result && !failed && (
        <Section title="Progress" id="public-progress">
          <div className={styles.sectionPad}>
            {status ? (
              <ScanTimeline stages={status.stages} progress={status.progress} />
            ) : (
              <SkeletonBlock lines={5} label="Loading scan status" />
            )}
            <p className={styles.hint}>Scanned images and PDFs are read with OCR, which can take a little longer.</p>
          </div>
        </Section>
      )}

      {failed && (
        <InlineNotice
          tone="danger"
          action={
            <ButtonLink to="/" size="sm" icon={<RotateCw size={14} aria-hidden />}>
              Try another file
            </ButtonLink>
          }
        >
          <CircleAlert size={16} aria-hidden />
          <span>{status?.error?.message ?? scan?.error?.message ?? 'An unexpected error occurred.'}</span>
        </InlineNotice>
      )}

      {completed && scan && (
        <>
          {scan.warnings && scan.warnings.length > 0 && (
            <div className={styles.gapBelow}>
              <InlineNotice tone="warning">
                <TriangleAlert size={16} aria-hidden />
                <span>{scan.warnings.join(' ')}</span>
              </InlineNotice>
            </div>
          )}

          <StatGroup label="Summary">
            <StatCard label="Items found" value={items.length} emphasis={items.length > 0 ? 'danger' : 'default'} />
            <StatCard label="Places in the file" value={findings.length} />
            <StatCard label="Kinds of data" value={countsByType(items).length} />
          </StatGroup>

          {items.length > 0 && (
            <ul className={styles.typeCounts} aria-label="Found by kind">
              {countsByType(items).map(([type, count]) => (
                <li key={type}>
                  <FindingBadge type={type} />
                  <span className={styles.typeCount}>{count}</span>
                </li>
              ))}
            </ul>
          )}

          {idItems.length > 0 && (
            <div className={styles.gapBelowLarge}>
              <Section
                title={idItems.length === 1 ? 'Is this ID number valid?' : 'Are these ID numbers valid?'}
                description="Each number is checked against the official structure and, for Aadhaar, its check digit."
                id="public-id-check"
              >
                <IdChecks items={idItems} />
              </Section>
            </div>
          )}

          {(result?.signatures.length ?? 0) > 0 && (
            <div className={styles.gapBelowLarge}>
              <Section
                title="Digital signatures"
                description="PDF signatures are checked against the CCA India roots, and Aadhaar Secure QR codes against UIDAI's own certificates. Revocation is not checked."
                id="public-signature"
              >
                <ul className={styles.signatureList}>
                  {result?.signatures.map((signature, index) => (
                    <li key={index} className={styles.signatureItem} data-status={signature.status}>
                      <strong>{signatureTitle(signature.status)}</strong>
                      {signature.signer && <span> · {signature.signer}</span>}
                      {signature.signedAt && <span> · {formatDateTime(signature.signedAt)}</span>}
                      <p className={styles.hint}>{signature.detail}</p>
                    </li>
                  ))}
                </ul>
                <p className={styles.hint}>
                  A valid signature proves who signed and that the signed data is unchanged. A printed seal, stamp or watermark in
                  a picture cannot be verified this way.
                </p>
              </Section>
            </div>
          )}

          <div className={styles.actionsGrid}>
            {findings.length > 0 && (
              <Section title="Redacted copy" id="public-redaction" ruled={false}>
                <div className={styles.card}>
                  {redaction?.status === 'COMPLETED' ? (
                    <>
                      {redaction.verified && (
                        <p className={styles.verified}>
                          <ShieldCheck size={16} aria-hidden />
                          {verificationText(redaction.verification?.method)}
                        </p>
                      )}
                      <Button
                        variant="primary"
                        icon={<Download size={16} aria-hidden />}
                        loading={busy === 'download'}
                        onClick={() => void downloadRedaction()}
                      >
                        Download redacted copy
                      </Button>
                      <p className={styles.hint}>
                        Automatic detection can miss details, especially in photos and handwriting. Look the copy over before you
                        share it.
                      </p>
                    </>
                  ) : redaction?.status === 'PROCESSING' ? (
                    <p className={styles.hint} role="status">
                      Creating the redacted copy and checking it…
                    </p>
                  ) : (
                    <>
                      <p className={styles.cardText}>
                        Get a copy of your file with every item below removed, everywhere it appears. Your original is not
                        changed.
                      </p>
                      {redaction?.status === 'FAILED' && (
                        <InlineNotice tone="danger">
                          <CircleAlert size={16} aria-hidden />
                          <span>{redaction.error ?? "The redacted copy couldn't be created."} Try again.</span>
                        </InlineNotice>
                      )}
                      <SegmentedControl<PublicRedactionAction>
                        label="How to remove values"
                        value={mode}
                        onChange={setMode}
                        options={[
                          { value: 'REDACT', label: 'Black out' },
                          { value: 'MASK', label: 'Mask (keep last digits)' },
                        ]}
                      />
                      {hasVisual && (
                        <p className={styles.hint}>Photos, QR codes and signatures are always blacked out completely.</p>
                      )}
                      <Button
                        variant="primary"
                        icon={<Eraser size={16} aria-hidden />}
                        loading={busy === 'redact'}
                        onClick={() => void createRedaction()}
                      >
                        Create redacted copy
                      </Button>
                    </>
                  )}
                </div>
              </Section>
            )}

            <Section title="Report" id="public-report" ruled={false}>
              <div className={styles.card}>
                <p className={styles.cardText}>A summary of what was found and where. It never contains the detected values.</p>
                <div className={styles.buttonRow}>
                  {REPORT_FORMATS.map(({ format, label }) => (
                    <Button
                      key={format}
                      size="sm"
                      icon={<Download size={14} aria-hidden />}
                      loading={busy === `report-${format}`}
                      disabled={!result?.reportAvailable}
                      onClick={() => void downloadReport(format)}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </div>
            </Section>
          </div>

          {items.length > 0 ? (
            <Section title="What was found" description="Select a row to see why it was flagged." id="public-findings">
              <DataTable<ResultItem>
                caption={`Personal data found in ${access.documentName}`}
                columns={ITEM_COLUMNS}
                rows={items}
                getRowId={(item) => item.key}
                onRowClick={(item) => setSelected(item)}
                selectedId={selected?.key ?? null}
              />
            </Section>
          ) : unreadable ? (
            <EmptyState
              icon={TriangleAlert}
              title="The text couldn't be read reliably"
              description={`${unreadablePageText(unreadablePages, scan.progress.totalPages)} too blurred, dark or grainy to read reliably, so personal data may be there without being detected. Don't treat this file as safe to share. Retake the photo in even light with the camera held steady, or upload the original file.`}
              action={
                <ButtonLink to="/" size="sm" icon={<RotateCw size={14} aria-hidden />}>
                  Check another file
                </ButtonLink>
              }
            />
          ) : (
            <EmptyState
              icon={ShieldCheck}
              title="Nothing found"
              description="No government ID numbers or other personal details were detected. Automated checks can still miss things, especially in poor-quality scans."
            />
          )}

          <p className={styles.expiry}>
            Your file and these results will be deleted automatically on {formatDateTime(result.expiresAt)}.
          </p>
        </>
      )}

      <Drawer open={selected !== null} onClose={() => setSelected(null)} title={selected ? 'Why this was flagged' : ''}>
        {selected && (
          <>
            {selected.occurrences.length > 1 && (
              <p className={styles.drawerNote}>
                Appears {pluralize(selected.occurrences.length, 'time')} in this file. The details below are for the clearest
                occurrence.
              </p>
            )}
            <FindingExplanation finding={selected.best} />
          </>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete your file now?"
        description="Your file, its results and any redacted copy are deleted permanently. This can't be undone."
        confirmLabel="Delete"
        tone="danger"
        loading={busy === 'delete'}
        onConfirm={() => void deleteUpload()}
        onCancel={() => setConfirmDelete(false)}
      />
    </PublicLayout>
  );
}
