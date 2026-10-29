import { Monitor, Moon, Sun } from 'lucide-react';
import { usePreferences } from '../../hooks/usePreferences';
import { SegmentedControl } from '../ui/SegmentedControl';
import { SettingsSection } from './SettingsSection';
import styles from './Settings.module.css';

export function InterfaceSettings() {
  const { theme, density, setTheme, setDensity } = usePreferences();
  return (
    <SettingsSection id="interface" title="Interface" description="Stored on this device only.">
      <div className={styles.form}>
        <SegmentedControl
          label="Theme"
          value={theme}
          onChange={setTheme}
          options={[
            { value: 'system', label: 'System', icon: <Monitor size={14} aria-hidden /> },
            { value: 'light', label: 'Light', icon: <Sun size={14} aria-hidden /> },
            { value: 'dark', label: 'Dark', icon: <Moon size={14} aria-hidden /> },
          ]}
        />
        <SegmentedControl
          label="Density"
          value={density}
          onChange={setDensity}
          options={[
            { value: 'comfortable', label: 'Comfortable' },
            { value: 'compact', label: 'Compact' },
          ]}
        />
      </div>
    </SettingsSection>
  );
}
