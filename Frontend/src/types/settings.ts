import type { RedactionAction } from './redaction';

/** Server-side preferences (scan behaviour and data retention). */
export interface ScanSettings {
  ocrEnabled: boolean;
  /** 0–1. Findings below this confidence are flagged as low priority. */
  confidenceThreshold: number;
  defaultRedactionMode: Exclude<RedactionAction, 'PRESERVE'>;
  retentionDays: number;
  autoDeleteEnabled: boolean;
}

/** Client-side, non-sensitive interface preferences. */
export type ThemePreference = 'system' | 'light' | 'dark';
export type DensityPreference = 'comfortable' | 'compact';

export interface InterfacePreferences {
  theme: ThemePreference;
  density: DensityPreference;
}
