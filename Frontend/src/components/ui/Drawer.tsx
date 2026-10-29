import type { ReactNode } from 'react';
import { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { IconButton } from './Button';
import styles from './Dialog.module.css';

interface DrawerProps {
  open: boolean;
  onClose(): void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  side?: 'right' | 'left';
  /** Hide the visual header (e.g. navigation drawer provides its own). */
  bare?: boolean;
}

export function Drawer({ open, onClose, title, subtitle, children, footer, side = 'right', bare }: DrawerProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(ref, open, onClose);

  if (!open) return null;

  return createPortal(
    <>
      <div className={styles.drawerBackdrop} onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={[styles.drawer, side === 'left' && styles.drawerLeft].filter(Boolean).join(' ')}
      >
        {bare ? (
          <h2 id={titleId} className="visually-hidden">
            {title}
          </h2>
        ) : (
          <div className={styles.drawerHeader}>
            <div className={styles.drawerTitle}>
              <h2 id={titleId} className={styles.title}>
                {title}
              </h2>
              {subtitle && <div className={styles.description}>{subtitle}</div>}
            </div>
            <IconButton label="Close panel" size="sm" onClick={onClose} data-focus-skip>
              <X size={16} aria-hidden />
            </IconButton>
          </div>
        )}
        <div className={bare ? styles.drawerBare : styles.drawerBody}>{children}</div>
        {footer && <div className={styles.drawerFooter}>{footer}</div>}
      </div>
    </>,
    document.body,
  );
}
