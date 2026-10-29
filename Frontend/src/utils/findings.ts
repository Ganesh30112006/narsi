import type { Finding, FindingLocation } from '../types/finding';
import { DETECTION_METHOD_LABELS } from './labels';

export function describeLocation(location: FindingLocation): string {
  const parts: string[] = [];
  if (location.page !== null) parts.push(`Page ${location.page}`);
  if (location.sheet) parts.push(location.sheet);
  if (location.cell) parts.push(`Cell ${location.cell}`);
  if (location.line !== null) parts.push(`Line ${location.line}`);
  return parts.join(' · ') || 'Location unavailable';
}

/** "Pattern + Context + Checksum" */
export function detectedBy(finding: Pick<Finding, 'detectionMethod' | 'detectionSignals'>): string {
  const signals = finding.detectionSignals.length > 0 ? finding.detectionSignals : [finding.detectionMethod];
  return signals.map((signal) => DETECTION_METHOD_LABELS[signal]).join(' + ');
}
