import { useEffect, useState } from 'react';
import { Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { usePermission } from '../../hooks/useAuth';
import { useToast } from '../../hooks/useToast';
import { toApiError } from '../../services/apiError';
import { findingApi } from '../../services/findingApi';
import { VISUAL_TYPES, type Finding } from '../../types/finding';
import { PII_TYPE_LABELS } from '../../utils/labels';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../ui/Dialog';
import { TextAreaField } from '../ui/Field';
import styles from './Findings.module.css';

interface MaskedValueProps {
  finding: Pick<Finding, 'id' | 'maskedValue' | 'piiType'>;
}

/**
 * Shows the backend-masked value. Users with the `pii:reveal` permission can request the raw
 * value through an audited reveal; it is held only in component memory and re-masked on expiry.
 */
export function MaskedValue({ finding }: MaskedValueProps) {
  // A photo, QR code or signature has no text value; the page preview shows where it is.
  const canReveal = usePermission('pii:reveal') && !VISUAL_TYPES.includes(finding.piiType);
  const { notify } = useToast();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [revealed, setRevealed] = useState<{ value: string; expiresAt: number } | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

  // Re-mask when the reveal expires or the finding changes.
  useEffect(() => {
    if (!revealed) return;
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((revealed.expiresAt - Date.now()) / 1000));
      setSecondsLeft(remaining);
      if (remaining === 0) setRevealed(null);
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [revealed]);

  useEffect(() => {
    setRevealed(null);
  }, [finding.id]);

  const confirmReveal = async () => {
    if (reason.trim().length < 5) {
      setReasonError('Describe why you need to see this value (at least 5 characters).');
      return;
    }
    setLoading(true);
    try {
      const result = await findingApi.reveal(finding.id, { reason: reason.trim() });
      setRevealed({ value: result.value, expiresAt: new Date(result.expiresAt).getTime() });
      setDialogOpen(false);
      setReason('');
    } catch (error) {
      const apiError = toApiError(error);
      if (apiError.kind === 'validation' && apiError.fieldErrors.reason) {
        setReasonError(apiError.fieldErrors.reason);
      } else {
        setDialogOpen(false);
        notify({ tone: 'error', title: 'Unable to reveal value', description: apiError.message });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <span className={styles.maskedValue}>
      <code className={styles.maskedCode} aria-label={revealed ? 'Revealed value' : 'Masked value'}>
        {revealed ? revealed.value : finding.maskedValue}
      </code>
      {revealed ? (
        <>
          <span className={styles.revealTimer} aria-live="polite">
            Hides in {secondsLeft}s
          </span>
          <Button size="sm" variant="ghost" icon={<EyeOff size={14} aria-hidden />} onClick={() => setRevealed(null)}>
            Hide
          </Button>
        </>
      ) : (
        canReveal && (
          <Button size="sm" variant="ghost" icon={<Eye size={14} aria-hidden />} onClick={() => setDialogOpen(true)}>
            Reveal
          </Button>
        )
      )}
      <ConfirmDialog
        open={dialogOpen}
        title={`Reveal ${PII_TYPE_LABELS[finding.piiType]} value?`}
        description="The full value will be shown for 30 seconds. This action is recorded in the audit log with your reason."
        confirmLabel="Reveal value"
        tone="warning"
        loading={loading}
        onConfirm={() => void confirmReveal()}
        onCancel={() => {
          setDialogOpen(false);
          setReasonError(null);
        }}
      >
        <TextAreaField
          label="Reason for access"
          hint="For example: verifying identity for case #1042."
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
            setReasonError(null);
          }}
          error={reasonError}
          maxLength={200}
          rows={3}
        />
        <p className={styles.revealNote}>
          <ShieldCheck size={14} aria-hidden />
          Avoid copying revealed values into other systems.
        </p>
      </ConfirmDialog>
    </span>
  );
}
