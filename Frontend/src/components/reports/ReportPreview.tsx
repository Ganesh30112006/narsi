import { useState } from 'react';
import { FileDown, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router';
import { usePermission } from '../../hooks/useAuth';
import { useToast } from '../../hooks/useToast';
import { toApiError } from '../../services/apiError';
import { reportApi } from '../../services/reportApi';
import type { Report, ReportExportFormat } from '../../types/report';
import { saveBlob } from '../../utils/file';
import { formatDateTime, formatNumber } from '../../utils/formatting';
import { CONFIDENCE_LABELS, DETECTION_METHOD_LABELS, PII_TYPE_LABELS, REPORT_REDACTION_LABELS } from '../../utils/labels';
import { sanitizeFileName } from '../../utils/security';
import { BarList } from '../charts/BarList';
import { StackedBar } from '../charts/StackedBar';
import { FindingBadge } from '../findings/FindingBadge';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { DescriptionList, Section } from '../ui/Layout';
import styles from './Reports.module.css';

const FORMATS: { format: ReportExportFormat; label: string }[] = [
  { format: 'pdf', label: 'Export PDF' },
  { format: 'json', label: 'Export JSON' },
  { format: 'csv', label: 'Export CSV' },
];

const CONFIDENCE_COLORS = { HIGH: '--chart-high', MEDIUM: '--chart-medium', LOW: '--chart-low' } as const;

export function ReportPreview({ report }: { report: Report }) {
  const canExport = usePermission('reports:export');
  const { notify } = useToast();
  const [exporting, setExporting] = useState<ReportExportFormat | null>(null);

  const exportAs = async (format: ReportExportFormat) => {
    setExporting(format);
    try {
      const { blob, fileName } = await reportApi.export(report.id, format);
      saveBlob(blob, sanitizeFileName(fileName ?? `govpii-report-${report.id}.${format}`));
      notify({ tone: 'success', title: 'Report generated', description: `${format.toUpperCase()} export downloaded.` });
    } catch (error) {
      notify({ tone: 'error', title: 'Unable to export report', description: toApiError(error).message });
    } finally {
      setExporting(null);
    }
  };

  return (
    <article className={styles.preview} aria-labelledby="report-title">
      <header className={styles.previewHeader}>
        <div>
          <p className={styles.eyebrow}>Scan report</p>
          <h2 id="report-title" className={styles.previewTitle}>
            {report.documentName}
          </h2>
        </div>
        {canExport && (
          <div className={styles.exports} role="group" aria-label="Export report">
            {FORMATS.map(({ format, label }) => (
              <Button
                key={format}
                size="sm"
                icon={<FileDown size={14} aria-hidden />}
                loading={exporting === format}
                disabled={exporting !== null && exporting !== format}
                onClick={() => void exportAs(format)}
              >
                {label}
              </Button>
            ))}
          </div>
        )}
      </header>

      <DescriptionList
        columns={2}
        items={[
          { label: 'Document', value: <Link to={`/app/documents/${report.documentId}`}>{report.documentName}</Link> },
          { label: 'Scan timestamp', value: formatDateTime(report.scanCompletedAt ?? report.generatedAt) },
          { label: 'Scanner version', value: <span className="mono">{report.scannerVersion}</span> },
          { label: 'Total findings', value: formatNumber(report.totalFindings) },
          { label: 'Pages', value: report.pageCount !== null ? formatNumber(report.pageCount) : '—' },
          {
            label: 'Processing time',
            value: report.metrics?.totalMs != null ? `${(report.metrics.totalMs / 1000).toFixed(1)} s` : '—',
          },
          { label: 'OCR engine', value: report.metrics?.ocrUsed ? (report.ocrEngineVersion ?? 'Used') : 'Not used' },
          {
            label: 'Redaction status',
            value: (
              <Badge
                tone={
                  report.redactionStatus === 'REDACTED'
                    ? 'success'
                    : report.redactionStatus === 'PARTIALLY_REDACTED'
                      ? 'warning'
                      : 'neutral'
                }
              >
                {REPORT_REDACTION_LABELS[report.redactionStatus]}
              </Badge>
            ),
          },
        ]}
      />

      {report.totalFindings === 0 ? (
        <p className={styles.none}>
          <ShieldCheck size={16} aria-hidden />
          No PII was detected in this document.
        </p>
      ) : (
        <div className={styles.charts}>
          <Section title="PII categories" id="report-categories">
            <div className={styles.chartBody}>
              <BarList
                label="Findings by PII category"
                data={report.categories.map((row) => ({
                  key: row.piiType,
                  label: <FindingBadge type={row.piiType} />,
                  text: PII_TYPE_LABELS[row.piiType],
                  value: row.count,
                }))}
              />
            </div>
          </Section>

          <Section title="Confidence distribution" id="report-confidence">
            <div className={styles.chartBody}>
              <StackedBar
                label="Findings by confidence level"
                segments={report.confidenceDistribution.map((row) => ({
                  key: row.level,
                  label: CONFIDENCE_LABELS[row.level],
                  value: row.count,
                  colorVar: CONFIDENCE_COLORS[row.level],
                }))}
              />
            </div>
          </Section>

          <div className={styles.chartPair}>
            <Section title="Page distribution" id="report-pages">
              <div className={styles.chartBody}>
                <BarList
                  label="Findings by page"
                  data={report.pageDistribution.map((row) => ({
                    key: String(row.page),
                    label: `Page ${row.page}`,
                    text: `Page ${row.page}`,
                    value: row.count,
                  }))}
                />
              </div>
            </Section>
            <Section title="Detection methods" id="report-methods">
              <div className={styles.chartBody}>
                <BarList
                  label="Findings by detection method"
                  data={report.detectionMethods.map((row) => ({
                    key: row.method,
                    label: DETECTION_METHOD_LABELS[row.method],
                    text: DETECTION_METHOD_LABELS[row.method],
                    value: row.count,
                  }))}
                />
              </div>
            </Section>
          </div>
        </div>
      )}

      <p className={styles.footnote}>Reports contain counts and locations only. Detected values are never included.</p>
    </article>
  );
}
