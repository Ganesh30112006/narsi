import type { FormEvent } from 'react';
import { useState } from 'react';
import { KeyRound, Trash2 } from 'lucide-react';
import { useResource } from '../../hooks/useResource';
import { useToast } from '../../hooks/useToast';
import { apiKeyApi } from '../../services/apiKeyApi';
import { toApiError } from '../../services/apiError';
import type { ApiKey, CreatedApiKey } from '../../types/apiKey';
import { formatRelativeTime } from '../../utils/formatting';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../ui/Dialog';
import { TextField } from '../ui/Field';
import { SkeletonBlock } from '../ui/Skeleton';
import { ErrorState, InlineNotice } from '../ui/StateViews';
import { SettingsSection } from './SettingsSection';
import styles from './Settings.module.css';

/** Keys that let another system upload files, scan them and fetch the masked results. */
export function ApiKeySettings() {
  const { notify } = useToast();
  const keys = useResource('api-keys', (signal) => apiKeyApi.list(signal));
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setNameError('Give the key a name, such as the system that will use it.');
      return;
    }
    setCreating(true);
    setNameError(null);
    try {
      const key = await apiKeyApi.create(name.trim());
      setCreated(key);
      setName('');
      keys.reload();
    } catch (caught) {
      const apiError = toApiError(caught);
      setNameError(apiError.fieldErrors.name ?? apiError.message);
    } finally {
      setCreating(false);
    }
  };

  const revoke = async () => {
    if (!revoking) return;
    setBusy(true);
    try {
      await apiKeyApi.revoke(revoking.id);
      notify({ tone: 'success', title: 'API key revoked' });
      if (created?.id === revoking.id) setCreated(null);
      keys.reload();
    } catch (caught) {
      notify({ tone: 'error', title: "Couldn't revoke the key", description: toApiError(caught).message });
    } finally {
      setBusy(false);
      setRevoking(null);
    }
  };

  return (
    <SettingsSection
      id="api-keys"
      title="API keys"
      description="Let another system upload files, scan them and fetch the masked results. A key can't reveal values, read the audit log, or see public uploads."
    >
      <div className={styles.stack}>
        {created && (
          <InlineNotice tone="success">
            <span>
              Copy this key now. It won't be shown again.
              <code className={styles.secret}>{created.key}</code>
              Send it as <code>Authorization: Bearer &lt;key&gt;</code>.
            </span>
          </InlineNotice>
        )}
        <form className={styles.form} onSubmit={create} noValidate>
          <TextField
            label="Key name"
            hint="For example the system or team that will use it."
            value={name}
            maxLength={80}
            onChange={(event) => setName(event.target.value)}
            error={nameError}
          />
          <div className={styles.actions}>
            <Button type="submit" variant="primary" icon={<KeyRound size={16} aria-hidden />} loading={creating}>
              Create key
            </Button>
          </div>
        </form>
        {keys.status === 'error' && keys.error ? (
          <ErrorState error={keys.error} subject="API keys" onRetry={keys.reload} compact />
        ) : !keys.data ? (
          <SkeletonBlock lines={2} label="Loading API keys" />
        ) : keys.data.length === 0 ? (
          <p className={styles.sessionMeta}>No API keys yet.</p>
        ) : (
          <ul className={styles.sessions} aria-label="API keys">
            {keys.data.map((key) => (
              <li key={key.id}>
                <KeyRound size={16} aria-hidden />
                <div className={styles.grow}>
                  <div className={styles.sessionDevice}>{key.name}</div>
                  <div className={styles.sessionMeta}>
                    {key.prefix}… · Created {formatRelativeTime(key.createdAt)} ·{' '}
                    {key.lastUsedAt ? `Last used ${formatRelativeTime(key.lastUsedAt)}` : 'Never used'}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={14} aria-hidden />}
                  onClick={() => setRevoking(key)}
                  aria-label={`Revoke ${key.name}`}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <ConfirmDialog
        open={revoking !== null}
        title="Revoke this key?"
        description={`Systems using "${revoking?.name ?? ''}" will stop working straight away.`}
        confirmLabel="Revoke key"
        tone="danger"
        loading={busy}
        onConfirm={() => void revoke()}
        onCancel={() => setRevoking(null)}
      />
    </SettingsSection>
  );
}
