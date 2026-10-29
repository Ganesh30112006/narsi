import { useState } from 'react';
import { Lock } from 'lucide-react';
import { usePermission } from '../../hooks/useAuth';
import { useToast } from '../../hooks/useToast';
import { toApiError } from '../../services/apiError';
import { systemApi } from '../../services/systemApi';
import type { ScanSettings } from '../../types/settings';
import { formatPercent } from '../../utils/formatting';
import { REDACTION_ACTION_DESCRIPTIONS } from '../../utils/labels';
import { Button } from '../ui/Button';
import { SelectField, Switch } from '../ui/Field';
import { SegmentedControl } from '../ui/SegmentedControl';
import { InlineNotice } from '../ui/StateViews';
import { SettingsSection } from './SettingsSection';
import styles from './Settings.module.css';

interface Props {
  settings: ScanSettings;
  onSaved(settings: ScanSettings): void;
}

function useSave(onSaved: Props['onSaved']) {
  const { notify } = useToast();
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const save = async (next: ScanSettings) => {
    setSaving(true);
    setFieldErrors({});
    try {
      const saved = await systemApi.updateSettings(next);
      onSaved(saved);
      notify({ tone: 'success', title: 'Settings saved' });
    } catch (caught) {
      const apiError = toApiError(caught);
      setFieldErrors(apiError.fieldErrors);
      notify({ tone: 'error', title: 'Settings not saved', description: apiError.message });
    } finally {
      setSaving(false);
    }
  };
  return { save, saving, fieldErrors };
}

function ManagedNotice() {
  return (
    <InlineNotice tone="info">
      <Lock size={14} aria-hidden />
      These settings are managed by your administrator.
    </InlineNotice>
  );
}

export function ScanPreferencesSection({ settings, onSaved }: Props) {
  const canManage = usePermission('settings:manage');
  const [draft, setDraft] = useState(settings);
  const { save, saving, fieldErrors } = useSave(onSaved);
  const dirty =
    draft.ocrEnabled !== settings.ocrEnabled ||
    draft.confidenceThreshold !== settings.confidenceThreshold ||
    draft.defaultRedactionMode !== settings.defaultRedactionMode;

  return (
    <SettingsSection id="scan-preferences" title="Scan preferences" description="Defaults applied to new scans and redactions.">
      <div className={styles.form}>
        {!canManage && <ManagedNotice />}
        <Switch
          label="Optical character recognition (OCR)"
          description="Read text from scanned pages and images. Scans take longer with OCR."
          checked={draft.ocrEnabled}
          disabled={!canManage}
          onChange={(ocrEnabled) => setDraft((current) => ({ ...current, ocrEnabled }))}
        />
        <div className={styles.rangeField}>
          <label htmlFor="confidence-threshold" className={styles.rangeLabel}>
            Confidence threshold <output htmlFor="confidence-threshold">{formatPercent(draft.confidenceThreshold)}</output>
          </label>
          <input
            id="confidence-threshold"
            type="range"
            min={0}
            max={100}
            step={5}
            value={Math.round(draft.confidenceThreshold * 100)}
            disabled={!canManage}
            aria-describedby="confidence-threshold-hint"
            onChange={(event) => setDraft((current) => ({ ...current, confidenceThreshold: Number(event.target.value) / 100 }))}
          />
          <p id="confidence-threshold-hint" className={styles.hint}>
            Findings below this confidence are not reported.
          </p>
          {fieldErrors.confidenceThreshold && <p className={styles.error}>{fieldErrors.confidenceThreshold}</p>}
        </div>
        <SegmentedControl
          label="Default redaction mode"
          value={draft.defaultRedactionMode}
          onChange={(mode) => setDraft((current) => ({ ...current, defaultRedactionMode: mode }))}
          disabled={!canManage}
          options={[
            { value: 'REDACT', label: 'Redact' },
            { value: 'MASK', label: 'Mask' },
          ]}
        />
        <p className={styles.hint}>{REDACTION_ACTION_DESCRIPTIONS[draft.defaultRedactionMode]}</p>
        {canManage && (
          <div className={styles.actions}>
            <Button
              variant="primary"
              disabled={!dirty}
              loading={saving}
              onClick={() =>
                void save({
                  ...settings,
                  ocrEnabled: draft.ocrEnabled,
                  confidenceThreshold: draft.confidenceThreshold,
                  defaultRedactionMode: draft.defaultRedactionMode,
                })
              }
            >
              Save preferences
            </Button>
          </div>
        )}
      </div>
    </SettingsSection>
  );
}

const RETENTION_OPTIONS = [30, 90, 180, 365, 730].map((days) => ({
  value: String(days),
  label: days < 365 ? `${days} days` : `${days / 365} year${days > 365 ? 's' : ''}`,
}));

export function RetentionSection({ settings, onSaved }: Props) {
  const canManage = usePermission('settings:manage');
  const [retentionDays, setRetentionDays] = useState(String(settings.retentionDays));
  const [autoDelete, setAutoDelete] = useState(settings.autoDeleteEnabled);
  const { save, saving, fieldErrors } = useSave(onSaved);
  const dirty = Number(retentionDays) !== settings.retentionDays || autoDelete !== settings.autoDeleteEnabled;
  const options = RETENTION_OPTIONS.some((option) => option.value === retentionDays)
    ? RETENTION_OPTIONS
    : [...RETENTION_OPTIONS, { value: retentionDays, label: `${retentionDays} days` }];

  return (
    <SettingsSection
      id="retention"
      title="Data retention"
      description="How long uploaded documents and scan results are kept. Audit logs follow your organisation's separate policy."
    >
      <div className={styles.form}>
        {!canManage && <ManagedNotice />}
        <SelectField
          label="Keep documents for"
          value={retentionDays}
          onChange={(value) => setRetentionDays(value || retentionDays)}
          options={options}
          disabled={!canManage}
          error={fieldErrors.retentionDays}
        />
        <Switch
          label="Delete documents automatically"
          description="When enabled, originals and sanitized copies are deleted after the retention period."
          checked={autoDelete}
          disabled={!canManage}
          onChange={setAutoDelete}
        />
        {autoDelete && (
          <InlineNotice tone="warning">Deleted documents cannot be recovered. Reports and audit entries are kept.</InlineNotice>
        )}
        {canManage && (
          <div className={styles.actions}>
            <Button
              variant="primary"
              disabled={!dirty}
              loading={saving}
              onClick={() => void save({ ...settings, retentionDays: Number(retentionDays), autoDeleteEnabled: autoDelete })}
            >
              Save retention
            </Button>
          </div>
        )}
      </div>
    </SettingsSection>
  );
}
