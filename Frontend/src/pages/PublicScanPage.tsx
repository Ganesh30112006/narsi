import { useState } from 'react';
import { Camera, CircleAlert, Clock, EyeOff, FileText, Languages, ShieldCheck, UserX } from 'lucide-react';
import { Link, useNavigate } from 'react-router';
import { FileDropzone } from '../components/documents/FileDropzone';
import { FindingBadge } from '../components/findings/FindingBadge';
import { PublicLayout } from '../components/layout/PublicLayout';
import { ProgressBar } from '../components/ui/ProgressBar';
import { InlineNotice } from '../components/ui/StateViews';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { toApiError } from '../services/apiError';
import { publicApi } from '../services/publicApi';
import { PII_TYPES } from '../types/finding';
import { validateFile } from '../utils/file';
import { formatBytes } from '../utils/formatting';
import { saveAccess } from '../utils/publicAccess';
import styles from './PublicPages.module.css';

/** Files per batch. Uploads are rate-limited per visitor, so a larger batch would mostly fail. */
export const MAX_BATCH = 5;

type Stage = { kind: 'idle' } | { kind: 'checking' | 'uploading'; file: File; progress: number; index: number; total: number };

interface BatchResult {
  name: string;
  scanId?: string;
  error?: string;
}

/** Public landing page: pick up to five files, upload them, and open their results. No account needed. */
export default function PublicScanPage() {
  useDocumentTitle('Scan a document for personal data');
  const navigate = useNavigate();
  const [stage, setStage] = useState<Stage>({ kind: 'idle' });
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchResult[]>([]);
  const busy = stage.kind !== 'idle';

  /** Uploads one file; returns its scan id, or throws with a message for the visitor. */
  const uploadOne = async (file: File, index: number, total: number): Promise<string> => {
    setStage({ kind: 'checking', file, progress: 0, index, total });
    const check = await validateFile(file);
    if (!check.ok) throw new Error(check.reason);
    setStage({ kind: 'uploading', file, progress: 0, index, total });
    try {
      const upload = await publicApi.upload(file, (progress) => setStage({ kind: 'uploading', file, progress, index, total }));
      saveAccess(upload.scanId, { token: upload.accessToken, documentName: upload.documentName, expiresAt: upload.expiresAt });
      return upload.scanId;
    } catch (caught) {
      throw new Error(toApiError(caught).message);
    }
  };

  const start = async (files: File[]) => {
    setError(null);
    setBatch([]);
    if (files.length > MAX_BATCH) {
      setError(`Choose up to ${MAX_BATCH} files at a time.`);
      return;
    }
    const results: BatchResult[] = [];
    for (const [index, file] of files.entries()) {
      try {
        results.push({ name: file.name, scanId: await uploadOne(file, index, files.length) });
      } catch (caught) {
        results.push({ name: file.name, error: caught instanceof Error ? caught.message : String(caught) });
      }
    }
    setStage({ kind: 'idle' });
    const only = results.length === 1 ? results[0] : undefined;
    if (only?.scanId) {
      navigate(`/results/${encodeURIComponent(only.scanId)}`);
    } else if (only) {
      setError(only.error ?? null);
    } else {
      setBatch(results);
    }
  };

  return (
    <PublicLayout>
      <section className={styles.hero} aria-labelledby="scan-title">
        <h1 id="scan-title" className={styles.heroTitle}>
          Check a document for personal data
        </h1>
        <p className={styles.heroLead}>
          Upload a file to find government ID numbers and other personal details in it. You'll see what was found, why, and you
          can download a redacted copy. No account needed.
        </p>
      </section>

      <div className={styles.uploadCard}>
        {stage.kind === 'idle' ? (
          <>
            <FileDropzone multiple onFiles={(files) => files.length > 0 && void start(files)} disabled={busy} />
            <p className={styles.photoTip}>
              <Camera size={14} aria-hidden />
              <span>
                Photographing a document? Use even light, hold the phone steady and fill the frame with the page. Blurred, dark or
                grainy photos can hide details from the check.
              </span>
            </p>
          </>
        ) : (
          <div className={styles.uploading} role="status" aria-live="polite">
            <span className={styles.uploadingIcon} aria-hidden>
              <FileText size={20} />
            </span>
            <div className={styles.uploadingBody}>
              <p className={styles.uploadingName}>
                {stage.total > 1 && `${stage.index + 1} of ${stage.total} · `}
                {stage.file.name}
              </p>
              <p className={styles.uploadingMeta}>
                {formatBytes(stage.file.size)} ·{' '}
                {stage.kind === 'checking' ? 'Checking the file…' : `Uploading… ${Math.round(stage.progress * 100)}%`}
              </p>
              <ProgressBar
                label={stage.kind === 'checking' ? 'Checking file' : 'Upload progress'}
                value={stage.kind === 'uploading' ? stage.progress : undefined}
              />
            </div>
          </div>
        )}
        {error && (
          <div className={styles.uploadError}>
            <InlineNotice tone="danger">
              <CircleAlert size={16} aria-hidden />
              <span>{error}</span>
            </InlineNotice>
          </div>
        )}
        {batch.length > 0 && (
          <ul className={styles.batchList} aria-label="Uploaded files">
            {batch.map((item, index) => (
              <li key={`${item.name}-${index}`}>
                <FileText size={16} aria-hidden />
                <span className={styles.batchName}>{item.name}</span>
                {item.scanId ? (
                  <Link to={`/results/${encodeURIComponent(item.scanId)}`}>View results</Link>
                ) : (
                  <span className={styles.batchError}>{item.error}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <ul className={styles.promises}>
        <li>
          <UserX size={18} aria-hidden />
          <span>
            <strong>No sign-up.</strong> Only this browser tab can open your results.
          </span>
        </li>
        <li>
          <EyeOff size={18} aria-hidden />
          <span>
            <strong>Masked results.</strong> Detected values are never shown in full.
          </span>
        </li>
        <li>
          <Clock size={18} aria-hidden />
          <span>
            <strong>Deleted in 24 hours.</strong> Or straight away, whenever you choose.
          </span>
        </li>
        <li>
          <Languages size={18} aria-hidden />
          <span>
            <strong>English, Hindi and Telugu.</strong> Bilingual ID documents are read in both scripts.
          </span>
        </li>
      </ul>

      <p className={styles.privacyNote}>
        <ShieldCheck size={14} aria-hidden />
        <span>
          Your file is processed on this service's own server and is not shared with anyone. The administrators who run the
          service can open uploaded files to keep it working and safe, and every time they do it is logged. Don't upload documents
          you aren't allowed to share with them.
        </span>
      </p>

      <section className={styles.detects} aria-labelledby="detects-title">
        <h2 id="detects-title" className={styles.sectionTitle}>
          What it looks for
        </h2>
        <ul className={styles.typeList}>
          {PII_TYPES.map((type) => (
            <li key={type}>
              <FindingBadge type={type} />
            </li>
          ))}
        </ul>
      </section>
    </PublicLayout>
  );
}
