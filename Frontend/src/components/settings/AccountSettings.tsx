import type { FormEvent } from 'react';
import { useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useToast } from '../../hooks/useToast';
import { toApiError } from '../../services/apiError';
import { authApi } from '../../services/authApi';
import { ROLE_LABELS } from '../../utils/labels';
import { Button } from '../ui/Button';
import { TextField } from '../ui/Field';
import { DescriptionList } from '../ui/Layout';
import { SettingsSection } from './SettingsSection';
import styles from './Settings.module.css';

export function AccountSettings() {
  const { user, updateUser } = useAuth();
  const { notify } = useToast();
  const [name, setName] = useState(user?.name ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (!user) return null;
  const dirty = name.trim() !== user.name;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Enter your name.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await authApi.updateProfile({ name: trimmed });
      updateUser(updated);
      notify({ tone: 'success', title: 'Profile updated' });
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.fieldErrors.name ?? apiError.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsSection id="account" title="Account" description="Your name appears in audit logs and on documents you upload.">
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          error={error}
          autoComplete="name"
          maxLength={80}
        />
        <DescriptionList
          items={[
            { label: 'Username', value: user.username },
            { label: 'Role', value: ROLE_LABELS[user.role] },
          ]}
        />
        <div className={styles.actions}>
          <Button type="submit" variant="primary" disabled={!dirty} loading={saving}>
            Save changes
          </Button>
        </div>
      </form>
    </SettingsSection>
  );
}
