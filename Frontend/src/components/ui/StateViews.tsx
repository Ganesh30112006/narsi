import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { CircleAlert, Inbox, Lock, RefreshCw, SearchX, WifiOff } from 'lucide-react';
import type { ApiError } from '../../services/apiError';
import { Button } from './Button';
import styles from './Misc.module.css';

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}

export function EmptyState({ icon: Icon = Inbox, title, description, action, compact }: EmptyStateProps) {
  return (
    <div className={[styles.state, compact && styles.stateCompact].filter(Boolean).join(' ')}>
      <span className={styles.stateIcon} aria-hidden>
        <Icon size={18} />
      </span>
      <h3 className={styles.stateTitle}>{title}</h3>
      {description && <p className={styles.stateDescription}>{description}</p>}
      {action && <div className={styles.stateAction}>{action}</div>}
    </div>
  );
}

/** Filtered lists that return nothing are not the same as "no data yet". */
export function NoResultsState({ onClear, what = 'results' }: { onClear?: () => void; what?: string }) {
  return (
    <EmptyState
      icon={SearchX}
      title={`No matching ${what}`}
      description="Try adjusting your search or filters."
      action={
        onClear && (
          <Button size="sm" onClick={onClear}>
            Clear filters
          </Button>
        )
      }
      compact
    />
  );
}

function describe(error: ApiError, subject: string): { icon: LucideIcon; title: string; description: string } {
  switch (error.kind) {
    case 'forbidden':
      return { icon: Lock, title: 'Access restricted', description: `You don't have permission to view ${subject}.` };
    case 'not_found':
      return { icon: SearchX, title: 'Not found', description: `We couldn't find ${subject}. It may have been deleted.` };
    case 'network':
      return { icon: WifiOff, title: 'Unable to connect', description: error.message };
    case 'timeout':
      return { icon: WifiOff, title: 'The server is taking too long', description: error.message };
    default:
      return { icon: CircleAlert, title: 'Something went wrong', description: `We couldn't load ${subject}. ${error.message}` };
  }
}

interface ErrorStateProps {
  error: ApiError;
  /** What failed to load, e.g. "findings" → "Unable to load findings". */
  subject: string;
  onRetry?: () => void;
  compact?: boolean;
}

export function ErrorState({ error, subject, onRetry, compact }: ErrorStateProps) {
  const { icon: Icon, title, description } = describe(error, subject);
  const retryable = onRetry && error.kind !== 'forbidden' && error.kind !== 'not_found';
  return (
    <div className={[styles.state, compact && styles.stateCompact].filter(Boolean).join(' ')} role="alert">
      <span className={[styles.stateIcon, styles.stateIconError].join(' ')} aria-hidden>
        <Icon size={18} />
      </span>
      <h3 className={styles.stateTitle}>{title}</h3>
      <p className={styles.stateDescription}>{description}</p>
      {retryable && (
        <div className={styles.stateAction}>
          <Button size="sm" icon={<RefreshCw size={14} aria-hidden />} onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
      {error.requestId && <p className={styles.stateReference}>Reference: {error.requestId}</p>}
    </div>
  );
}

/** Inline, non-blocking notice (e.g. "Showing last known status"). */
export function InlineNotice({
  tone = 'info',
  children,
  action,
}: {
  tone?: 'info' | 'warning' | 'danger' | 'success';
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={[styles.notice, styles[`notice_${tone}`]].join(' ')} role={tone === 'danger' ? 'alert' : 'status'}>
      <div className={styles.noticeBody}>{children}</div>
      {action}
    </div>
  );
}
