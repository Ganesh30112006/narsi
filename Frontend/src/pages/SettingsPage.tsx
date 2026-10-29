import { AccountSettings } from '../components/settings/AccountSettings';
import { ApiKeySettings } from '../components/settings/ApiKeySettings';
import { InterfaceSettings } from '../components/settings/InterfaceSettings';
import { RetentionSection, ScanPreferencesSection } from '../components/settings/ScanSettingsSections';
import { SecuritySettings } from '../components/settings/SecuritySettings';
import { SettingsSection } from '../components/settings/SettingsSection';
import { PageHeader } from '../components/ui/Layout';
import { SkeletonBlock } from '../components/ui/Skeleton';
import { ErrorState } from '../components/ui/StateViews';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useResource } from '../hooks/useResource';
import { systemApi } from '../services/systemApi';

export default function SettingsPage() {
  useDocumentTitle('Settings');
  const settings = useResource('settings', (signal) => systemApi.getSettings(signal), { staleTimeMs: 60_000 });

  return (
    <>
      <PageHeader title="Settings" description="Manage your account, security and how documents are scanned." />
      <AccountSettings />
      <SecuritySettings />
      <ApiKeySettings />
      {settings.status === 'error' && settings.error ? (
        <SettingsSection id="scan-preferences" title="Scan preferences and retention">
          <ErrorState error={settings.error} subject="scan settings" onRetry={settings.reload} compact />
        </SettingsSection>
      ) : settings.data ? (
        <>
          <ScanPreferencesSection settings={settings.data} onSaved={(saved) => settings.setData(() => saved)} />
          <RetentionSection settings={settings.data} onSaved={(saved) => settings.setData(() => saved)} />
        </>
      ) : (
        <SettingsSection id="scan-preferences" title="Scan preferences">
          <SkeletonBlock lines={4} label="Loading scan settings" />
        </SettingsSection>
      )}
      <InterfaceSettings />
    </>
  );
}
