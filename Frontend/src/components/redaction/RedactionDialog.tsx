import type { ReactNode } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { CircleCheck, Download, FileCheck, Info, ShieldCheck } from 'lucide-react';
import { useResource } from '../../hooks/useResource';
import { useToast } from '../../hooks/useToast';
import { toApiError } from '../../services/apiError';
import { documentApi } from '../../services/documentApi';
import { redactionApi } from '../../services/redactionApi';
import { systemApi } from '../../services/systemApi';
import type { Finding } from '../../types/finding';
import type { Redaction, RedactionAction } from '../../types/redaction';
import { saveBlob } from '../../utils/file';
import { pluralize } from '../../utils/formatting';
import { verificationText } from '../../utils/publicResults';
import { REDACTION_ACTION_DESCRIPTIONS, REDACTION_ACTION_LABELS } from '../../utils/labels';
import { sanitizeFileName } from '../../utils/security';
import { FindingBadge } from '../findings/FindingBadge';
import { Button, ButtonLink } from '../ui/Button';
import { Dialog } from '../ui/Dialog';
import { InlineNotice } from '../ui/StateViews';
import { ProgressBar } from '../ui/ProgressBar';
import styles from './Redaction.module.css';

type Step = 'select' | 'confirm' | 'processing' | 'done';

interface RedactionDialogProps {
  onClose(): void;
  documentId: string;
  documentName: string;
  scanId: string;
  findings: Finding[];
  onCompleted?(redaction: Redaction): void;
}

const ACTIONS: RedactionAction[] = ['REDACT', 'MASK', 'PRESERVE'];
const POLL_MS = 1000;

/** Mount only while open — state is initialised on mount. */
export function RedactionDialog({ onClose, documentId, documentName, scanId, findings, onCompleted }: RedactionDialogProps) {
  const { notify } = useToast();
  const settings = useResource('settings', (signal) => systemApi.getSettings(signal), { staleTimeMs: 60_000 });
  const defaultAction: RedactionAction = settings.data?.defaultRedactionMode ?? 'REDACT';

  const [step, setStep] = useState<Step>('select');
  const [actions, setActions] = useState<Record<string, RedactionAction>>(() =>
    Object.fromEntries(findings.map((finding) => [finding.id, defaultAction])),
  );
  const touched = useRef(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [redaction, setRedaction] = useState<Redaction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const selectAllRef = useRef<HTMLInputElement>(null);

  // Apply the organisation's default mode once settings arrive, unless the user already made choices.
  useEffect(() => {
    if (touched.current) return;
    setActions(Object.fromEntries(findings.map((finding) => [finding.id, defaultAction])));
  }, [defaultAction, findings]);

  // Poll until the sanitized copy is ready.
  useEffect(() => {
    if (step !== 'processing' || !redaction || redaction.status !== 'PROCESSING') return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      redactionApi
        .get(redaction.id, controller.signal)
        .then(setRedaction)
        .catch((caught: unknown) => {
          const apiError = toApiError(caught);
          if (apiError.kind !== 'cancelled') setError(apiError.message);
        });
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [step, redaction]);

  useEffect(() => {
    if (!redaction || step !== 'processing') return;
    if (redaction.status === 'COMPLETED') {
      setStep('done');
      onCompleted?.(redaction);
      notify({ tone: 'success', title: 'Redaction completed', description: redaction.sanitizedFileName ?? undefined });
    } else if (redaction.status === 'FAILED') {
      setError(redaction.error ?? 'The sanitized copy could not be created.');
    }
  }, [redaction, step, onCompleted, notify]);

  const counts = useMemo(() => {
    const result: Record<RedactionAction, number> = { REDACT: 0, MASK: 0, PRESERVE: 0 };
    findings.forEach((finding) => {
      result[actions[finding.id] ?? defaultAction] += 1;
    });
    return result;
  }, [actions, findings, defaultAction]);

  const allSelected = findings.length > 0 && selected.size === findings.length;
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = selected.size > 0 && !allSelected;
  }, [selected, allSelected]);

  const applyToSelected = (action: RedactionAction) => {
    touched.current = true;
    setActions((current) => {
      const next = { ...current };
      selected.forEach((id) => {
        next[id] = action;
      });
      return next;
    });
  };

  const submit = async () => {
    setStep('processing');
    setError(null);
    try {
      const created = await redactionApi.create({
        documentId,
        scanId,
        items: findings.map((finding) => ({ findingId: finding.id, action: actions[finding.id] ?? defaultAction })),
      });
      setRedaction(created);
    } catch (caught) {
      setError(toApiError(caught).message);
    }
  };

  const downloadSanitized = async () => {
    if (!redaction?.sanitizedDocumentId) return;
    setDownloading(true);
    try {
      const { blob, fileName } = await documentApi.download(redaction.sanitizedDocumentId);
      saveBlob(blob, sanitizeFileName(fileName ?? redaction.sanitizedFileName ?? 'sanitized-document'));
    } catch (caught) {
      notify({ tone: 'error', title: 'Download failed', description: toApiError(caught).message });
    } finally {
      setDownloading(false);
    }
  };

  const removed = counts.REDACT + counts.MASK;
  const busy = step === 'processing' && !error;

  const titles: Record<Step, string> = {
    select: 'Redact sensitive data',
    confirm: 'Create sanitized copy?',
    processing: error ? 'Redaction failed' : 'Creating sanitized copy',
    done: 'Redaction completed',
  };

  let body: ReactNode;
  let footer: ReactNode;

  if (step === 'select') {
    body = (
      <>
        <div className={styles.toolbar}>
          <label className={styles.selectAll}>
            <input
              ref={selectAllRef}
              type="checkbox"
              checked={allSelected}
              onChange={() => setSelected(allSelected ? new Set() : new Set(findings.map((finding) => finding.id)))}
            />
            <span>{selected.size > 0 ? `${selected.size} selected` : 'Select findings'}</span>
          </label>
          <div className={styles.bulk} role="group" aria-label="Apply to selected findings">
            {ACTIONS.map((action) => (
              <Button
                key={action}
                size="sm"
                variant="secondary"
                disabled={selected.size === 0}
                onClick={() => applyToSelected(action)}
              >
                {REDACTION_ACTION_LABELS[action]} selected
              </Button>
            ))}
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              touched.current = true;
              setActions(Object.fromEntries(findings.map((finding) => [finding.id, 'REDACT' as const])));
            }}
          >
            Redact all
          </Button>
        </div>
        <ul className={styles.items} aria-label="Findings">
          {findings.map((finding) => {
            const action = actions[finding.id] ?? defaultAction;
            return (
              <li key={finding.id} className={styles.item} data-action={action}>
                <input
                  type="checkbox"
                  checked={selected.has(finding.id)}
                  aria-label={`Select ${finding.piiType} on page ${finding.location.page ?? '—'}`}
                  onChange={(event) =>
                    setSelected((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(finding.id);
                      else next.delete(finding.id);
                      return next;
                    })
                  }
                />
                <span className={styles.itemType}>
                  <FindingBadge type={finding.piiType} />
                </span>
                <code className={styles.itemValue}>{finding.maskedValue}</code>
                <span className={styles.itemPage}>{finding.location.page !== null ? `Page ${finding.location.page}` : '—'}</span>
                <select
                  className={styles.itemAction}
                  value={action}
                  aria-label={`Action for ${finding.piiType} ${finding.maskedValue}`}
                  onChange={(event) => {
                    touched.current = true;
                    setActions((current) => ({ ...current, [finding.id]: event.target.value as RedactionAction }));
                  }}
                >
                  {ACTIONS.map((option) => (
                    <option key={option} value={option}>
                      {REDACTION_ACTION_LABELS[option]}
                    </option>
                  ))}
                </select>
              </li>
            );
          })}
        </ul>
        <p className={styles.counts} aria-live="polite">
          {counts.REDACT} to redact · {counts.MASK} to mask · {counts.PRESERVE} preserved
        </p>
      </>
    );
    footer = (
      <>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={() => setStep('confirm')} disabled={removed === 0}>
          Continue
        </Button>
      </>
    );
  } else if (step === 'confirm') {
    body = (
      <div className={styles.confirm}>
        <p className={styles.confirmLead}>{pluralize(removed, 'finding')} selected for removal</p>
        <dl className={styles.confirmCounts}>
          {ACTIONS.map((action) => (
            <div key={action}>
              <dt>{REDACTION_ACTION_LABELS[action]}</dt>
              <dd>{counts[action]}</dd>
              <dd className={styles.confirmHint}>{REDACTION_ACTION_DESCRIPTIONS[action]}</dd>
            </div>
          ))}
        </dl>
        <InlineNotice tone="info">
          <Info size={16} aria-hidden />
          <span>This creates a sanitized copy. The original document will remain unchanged.</span>
        </InlineNotice>
      </div>
    );
    footer = (
      <>
        <Button onClick={() => setStep('select')}>Back</Button>
        <Button variant="primary" onClick={() => void submit()}>
          Create sanitized copy
        </Button>
      </>
    );
  } else if (step === 'processing') {
    body = error ? (
      <InlineNotice tone="danger">{error}</InlineNotice>
    ) : (
      <div className={styles.processing} role="status">
        <ProgressBar label="Creating sanitized copy" size="md" />
        <p>
          Applying {pluralize(removed, 'change')} to a copy of {documentName}…
        </p>
      </div>
    );
    footer = error ? (
      <>
        <Button onClick={onClose}>Close</Button>
        <Button variant="primary" onClick={() => void submit()}>
          Try again
        </Button>
      </>
    ) : null;
  } else {
    body = (
      <div className={styles.done}>
        <span className={styles.doneIcon} aria-hidden>
          <CircleCheck size={20} />
        </span>
        <p className={styles.doneLead}>
          {pluralize((redaction?.counts.redacted ?? 0) + (redaction?.counts.masked ?? 0), 'finding')} removed
        </p>
        <dl className={styles.versions}>
          <div>
            <dt>Original document</dt>
            <dd>{documentName}</dd>
            <dd className={styles.versionNote}>Unchanged</dd>
          </div>
          <div className={styles.versionSanitized}>
            <dt>
              <FileCheck size={14} aria-hidden /> Sanitized document
            </dt>
            <dd>{redaction?.sanitizedFileName}</dd>
            <dd className={styles.versionNote}>
              {redaction?.counts.redacted ?? 0} redacted · {redaction?.counts.masked ?? 0} masked ·{' '}
              {redaction?.counts.preserved ?? 0} preserved
            </dd>
          </div>
        </dl>
        {redaction?.verified && (
          <p className={styles.verified}>
            <ShieldCheck size={14} aria-hidden />
            {verificationText(redaction.verification?.method)}
          </p>
        )}
      </div>
    );
    footer = (
      <>
        {redaction?.sanitizedDocumentId && (
          <ButtonLink to={`/app/documents/${redaction.sanitizedDocumentId}`} variant="secondary" onClick={onClose}>
            View sanitized copy
          </ButtonLink>
        )}
        <Button
          variant="primary"
          icon={<Download size={16} aria-hidden />}
          loading={downloading}
          onClick={() => void downloadSanitized()}
        >
          Download sanitized copy
        </Button>
      </>
    );
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={titles[step]}
      description={step === 'select' ? `Choose how each finding in ${documentName} is handled in the sanitized copy.` : undefined}
      wide={step === 'select'}
      dismissible={!busy}
      footer={footer}
    >
      {body}
    </Dialog>
  );
}
