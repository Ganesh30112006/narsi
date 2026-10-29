import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-react';
import type { ToastTone } from '../../app/providers/contexts';
import styles from './Toast.module.css';

export interface ToastItem {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;
}

const ICONS = { success: CircleCheck, warning: TriangleAlert, error: CircleAlert, info: Info } as const;
const TONE_LABEL: Record<ToastTone, string> = { success: 'Success', warning: 'Warning', error: 'Error', info: 'Notice' };

interface ToastViewportProps {
  toasts: ToastItem[];
  onDismiss(id: string): void;
}

/**
 * Two live regions: errors are announced assertively, everything else politely.
 */
export function ToastViewport({ toasts, onDismiss }: ToastViewportProps) {
  const render = (toast: ToastItem) => {
    const Icon = ICONS[toast.tone];
    return (
      <div key={toast.id} className={[styles.toast, styles[toast.tone]].join(' ')}>
        <Icon size={16} className={styles.icon} aria-hidden />
        <div className={styles.content}>
          <span className="visually-hidden">{TONE_LABEL[toast.tone]}: </span>
          <p className={styles.title}>{toast.title}</p>
          {toast.description && <p className={styles.description}>{toast.description}</p>}
        </div>
        <button type="button" className={styles.close} onClick={() => onDismiss(toast.id)} aria-label="Dismiss notification">
          <X size={14} aria-hidden />
        </button>
      </div>
    );
  };

  return (
    <div className={styles.viewport}>
      <div role="status" aria-live="polite" className={styles.stack}>
        {toasts.filter((toast) => toast.tone !== 'error').map(render)}
      </div>
      <div role="alert" aria-live="assertive" className={styles.stack}>
        {toasts.filter((toast) => toast.tone === 'error').map(render)}
      </div>
    </div>
  );
}
