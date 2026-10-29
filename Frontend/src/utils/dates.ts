export type DateRangePreset = '' | '1d' | '7d' | '30d' | '90d';

export const DATE_RANGE_OPTIONS: { value: Exclude<DateRangePreset, ''>; label: string }[] = [
  { value: '1d', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
];

/** Converts a preset into an inclusive YYYY-MM-DD lower bound. */
export function presetToFromDate(preset: DateRangePreset, now: Date = new Date()): string | undefined {
  if (!preset) return undefined;
  const days = Number(preset.replace('d', ''));
  const from = new Date(now.getTime() - days * 24 * 3600 * 1000);
  return from.toISOString().slice(0, 10);
}
