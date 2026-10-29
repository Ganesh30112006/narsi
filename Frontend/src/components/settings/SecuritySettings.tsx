import type { FormEvent } from 'react';
import { useState } from 'react';
import { Check, LogOut, Monitor } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useAuth } from '../../hooks/useAuth';
import { useResource } from '../../hooks/useResource';
import { useToast } from '../../hooks/useToast';
import { toApiError } from '../../services/apiError';
import { authApi } from '../../services/authApi';
import { formatRelativeTime } from '../../utils/formatting';
import { PASSWORD_RULES, validateNewPassword } from '../../utils/validation';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../ui/Dialog';
import { PasswordField } from '../ui/Field';
import { SkeletonBlock } from '../ui/Skeleton';
import { ErrorState } from '../ui/StateViews';
import { SettingsSection } from './SettingsSection';
import styles from './Settings.module.css';

function ChangePasswordForm() {
  const { notify } = useToast();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const [saving, setSaving] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const validation = {
      current: current ? undefined : 'Enter your current password.',
      next: validateNewPassword(next) ?? undefined,
      confirm: confirm === next ? undefined : "Passwords don't match.",
    };
    setErrors(validation);
    if (validation.current || validation.next || validation.confirm) return;
    setSaving(true);
    try {
      await authApi.changePassword({ currentPassword: current, newPassword: next });
      setCurrent('');
      setNext('');
      setConfirm('');
      notify({ tone: 'success', title: 'Password changed' });
    } catch (caught) {
      const apiError = toApiError(caught);
      setErrors({
        current: apiError.fieldErrors.currentPassword,
        next: apiError.fieldErrors.newPassword ?? (apiError.kind === 'validation' ? undefined : apiError.message),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={onSubmit} noValidate>
      <h3 className={styles.subheading}>Change password</h3>
      <PasswordField
        label="Current password"
        autoComplete="current-password"
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
        error={errors.current}
      />
      <PasswordField
        label="New password"
        autoComplete="new-password"
        value={next}
        onChange={(event) => setNext(event.target.value)}
        error={errors.next}
      />
      <ul className={styles.rules} aria-label="Password requirements">
        {PASSWORD_RULES.map((rule) => {
          const met = rule.test(next);
          return (
            <li key={rule.id} data-met={met}>
              <Check size={12} aria-hidden />
              {rule.label}
              <span className="visually-hidden">{met ? ' — met' : ' — not met'}</span>
            </li>
          );
        })}
      </ul>
      <PasswordField
        label="Confirm new password"
        autoComplete="new-password"
        value={confirm}
        onChange={(event) => setConfirm(event.target.value)}
        error={errors.confirm}
      />
      <div className={styles.actions}>
        <Button type="submit" variant="primary" loading={saving} disabled={!current || !next || !confirm}>
          Update password
        </Button>
      </div>
    </form>
  );
}

function Sessions() {
  const { endSession } = useAuth();
  const navigate = useNavigate();
  const { notify } = useToast();
  const sessions = useResource('sessions', (signal) => authApi.listSessions(signal));
  const [confirming, setConfirming] = useState(false);
  const [revoking, setRevoking] = useState(false);

  const revokeAll = async () => {
    setRevoking(true);
    try {
      await authApi.revokeAllSessions();
      endSession();
      navigate('/admin/login', { replace: true });
    } catch (caught) {
      notify({ tone: 'error', title: 'Unable to sign out of all sessions', description: toApiError(caught).message });
      setRevoking(false);
      setConfirming(false);
    }
  };

  return (
    <div className={styles.form}>
      <h3 className={styles.subheading}>Active sessions</h3>
      {sessions.status === 'error' && sessions.error ? (
        <ErrorState error={sessions.error} subject="sessions" onRetry={sessions.reload} compact />
      ) : !sessions.data ? (
        <SkeletonBlock lines={3} label="Loading sessions" />
      ) : (
        <ul className={styles.sessions}>
          {sessions.data.map((session) => (
            <li key={session.id}>
              <Monitor size={16} aria-hidden />
              <div>
                <div className={styles.sessionDevice}>
                  {session.device}
                  {session.current && <Badge tone="success">This device</Badge>}
                </div>
                <div className={styles.sessionMeta}>
                  {session.location ?? 'Unknown location'} · Active {formatRelativeTime(session.lastActiveAt)}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div>
        <Button variant="dangerOutline" icon={<LogOut size={16} aria-hidden />} onClick={() => setConfirming(true)}>
          Sign out of all sessions
        </Button>
      </div>
      <ConfirmDialog
        open={confirming}
        title="Sign out everywhere?"
        description="All active sessions, including this one, will be ended. You'll need to sign in again."
        confirmLabel="Sign out everywhere"
        tone="danger"
        loading={revoking}
        onConfirm={() => void revokeAll()}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}

export function SecuritySettings() {
  return (
    <SettingsSection id="security" title="Security" description="Manage your password and where you're signed in.">
      <div className={styles.stack}>
        <ChangePasswordForm />
        <hr />
        <Sessions />
      </div>
    </SettingsSection>
  );
}
