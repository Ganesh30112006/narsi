import type { HealthCheck } from '../types/api';

/** Plain names for the dependencies the health endpoint checks. */
const COMPONENTS: Record<string, string> = {
  database: 'Database',
  storage: 'File storage',
  broker: 'Job queue',
  ocr: 'Text recognition',
  deep_ocr: 'Photo text recognition',
  restorer: 'Photo restoration',
  gpu: 'GPU acceleration',
  ner: 'Name detection',
  visual: 'Photo, QR code and signature detection',
};

/** "Photo text recognition: PP-OCR not installed; …" for every check that is not healthy. */
export function degradedSummary(checks: HealthCheck[] | undefined): string[] {
  return (checks ?? [])
    .filter((check) => check.status !== 'healthy')
    .map((check) => {
      const name = COMPONENTS[check.name] ?? check.name;
      return check.detail ? `${name}: ${check.detail}` : name;
    });
}
