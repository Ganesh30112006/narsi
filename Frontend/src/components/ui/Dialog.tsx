import type { ReactNode, RefObject } from 'react';
import { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Info, TriangleAlert, X } from 'lucide-react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { Button, IconButton } from './Button';
import styles from './Dialog.module.css';

interface DialogProps {
  open: boolean;
  onClose(): void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  /** Prevent closing via Escape/backdrop (e.g. while a request is running). */
  dismissible?: boolean;
  initialFocusRef?: RefObject<HTMLElement | null>;
  role?: 'dialog' | 'alertdialog';
  tone?: 'danger' | 'warning' | 'info';
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  wide,
  dismissible = true,
  initialFocusRef,
  role = 'dialog',
  tone,
}: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useFocusTrap(ref, open, () => dismissible && onClose(), initialFocusRef);

  if (!open) return null;

  const ToneIcon = tone === 'info' ? Info : TriangleAlert;

  return createPortal(
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && dismissible) onClose();
      }}
    >
      <div
        ref={ref}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={[styles.dialog, wide && styles.wide].filter(Boolean).join(' ')}
      >
        <div className={styles.header}>
          <div>
            {tone && (
              <span className={[styles.toneIcon, styles[tone]].join(' ')} aria-hidden>
                <ToneIcon size={16} />
              </span>
            )}
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className={styles.description}>
                {description}
              </p>
            )}
          </div>
          {dismissible && (
            <IconButton label="Close dialog" size="sm" onClick={onClose} data-focus-skip>
              <X size={16} aria-hidden />
            </IconButton>
          )}
        </div>
        {children && <div className={styles.body}>{children}</div>}
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: 'danger' | 'warning' | 'info';
  loading?: boolean;
  confirmDisabled?: boolean;
  onConfirm(): void;
  onCancel(): void;
}

/** Confirmation for sensitive or destructive actions. Focus starts on Cancel — the safe choice. */
export function ConfirmDialog({
  open,
  title,
  description,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  tone = 'info',
  loading = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      description={description}
      role="alertdialog"
      tone={tone}
      dismissible={!loading}
      initialFocusRef={cancelRef}
      footer={
        <>
          <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === 'danger' ? 'danger' : 'primary'}
            onClick={onConfirm}
            loading={loading}
            disabled={confirmDisabled}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
