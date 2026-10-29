import { ScanSearch, Upload } from 'lucide-react';
import { BarList } from '../components/charts/BarList';
import { RecentActivity } from '../components/dashboard/RecentActivity';
import { FindingBadge } from '../components/findings/FindingBadge';
import { RecentScansTable } from '../components/scans/RecentScansTable';
import { ButtonLink } from '../components/ui/Button';
import { PageHeader, Section, StatCard, StatGroup } from '../components/ui/Layout';
import { Skeleton, SkeletonBlock } from '../components/ui/Skeleton';
import { EmptyState, ErrorState } from '../components/ui/StateViews';
import { useAuth } from '../hooks/useAuth';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useResource } from '../hooks/useResource';
import { systemApi } from '../services/systemApi';
import { firstName, formatNumber, formatPercent, greeting } from '../utils/formatting';
import { PII_TYPE_LABELS } from '../utils/labels';
import styles from './Pages.module.css';

export default function DashboardPage() {
  useDocumentTitle('Dashboard');
  const { user, can } = useAuth();
  const summary = useResource('dashboard', (signal) => systemApi.getDashboardSummary(signal));
  const canUpload = can('documents:upload');

  const scanAction = canUpload && (
    <ButtonLink to="/app/documents/upload" variant="primary" icon={<ScanSearch size={16} aria-hidden />}>
      Scan a document
    </ButtonLink>
  );

  return (
    <>
      <PageHeader
        title={`${greeting()}, ${user ? firstName(user.name) : ''}`}
        description="Monitor document scanning and privacy findings."
        actions={scanAction}
      />

      {summary.status === 'error' && summary.error && !summary.data ? (
        <ErrorState error={summary.error} subject="the dashboard summary" onRetry={summary.reload} />
      ) : (
        <div className={styles.stack}>
          <StatGroup label="Summary">
            {summary.data ? (
              <>
                <StatCard label="Documents scanned" value={formatNumber(summary.data.stats.documentsScanned)} />
                <StatCard
                  label="Documents with PII"
                  value={formatNumber(summary.data.stats.documentsWithPii)}
                  hint={
                    summary.data.stats.documentsScanned > 0
                      ? `${formatPercent(summary.data.stats.documentsWithPii / summary.data.stats.documentsScanned)} of scanned`
                      : undefined
                  }
                />
                <StatCard label="PII findings" value={formatNumber(summary.data.stats.totalFindings)} />
                <StatCard
                  label="High-confidence findings"
                  value={formatNumber(summary.data.stats.highConfidenceFindings)}
                  emphasis={summary.data.stats.highConfidenceFindings > 0 ? 'danger' : 'default'}
                />
              </>
            ) : (
              ['Documents scanned', 'Documents with PII', 'PII findings', 'High-confidence findings'].map((label) => (
                <StatCard key={label} label={label} value={<Skeleton width={56} height={28} />} />
              ))
            )}
          </StatGroup>

          <Section
            title="Recent scans"
            id="recent-scans"
            actions={
              <ButtonLink to="/app/documents" size="sm" variant="ghost">
                All documents
              </ButtonLink>
            }
          >
            {!summary.data ? (
              <div className={styles.sectionPad}>
                <SkeletonBlock lines={4} label="Loading recent scans" />
              </div>
            ) : summary.data.recentScans.length === 0 ? (
              <EmptyState
                icon={Upload}
                title="No scans yet"
                description="Upload a document to run your first scan."
                action={scanAction}
                compact
              />
            ) : (
              <RecentScansTable scans={summary.data.recentScans} />
            )}
          </Section>

          <div className={styles.twoColumn}>
            <Section title="PII distribution" description="Findings by category across all scans" id="pii-distribution">
              <div className={styles.sectionPad}>
                {!summary.data ? (
                  <SkeletonBlock lines={6} label="Loading distribution" />
                ) : summary.data.stats.totalFindings === 0 ? (
                  <p className="muted">No findings have been detected yet.</p>
                ) : (
                  <BarList
                    label="Findings by PII type"
                    data={summary.data.piiDistribution.map((row) => ({
                      key: row.piiType,
                      label: <FindingBadge type={row.piiType} />,
                      text: PII_TYPE_LABELS[row.piiType],
                      value: row.count,
                    }))}
                  />
                )}
              </div>
            </Section>

            <Section
              title="Recent activity"
              description={can('audit:read') ? 'Latest actions across the workspace' : 'Your latest actions'}
              id="recent-activity"
            >
              {!summary.data ? (
                <div className={styles.sectionPad}>
                  <SkeletonBlock lines={5} label="Loading activity" />
                </div>
              ) : summary.data.recentActivity.length === 0 ? (
                <p className={[styles.sectionPad, 'muted'].join(' ')}>No activity recorded yet.</p>
              ) : (
                <>
                  <RecentActivity entries={summary.data.recentActivity} />
                  {can('audit:read') && (
                    <ButtonLink to="/app/audit-logs" size="sm" variant="ghost" className={styles.moreLink}>
                      View audit log
                    </ButtonLink>
                  )}
                </>
              )}
            </Section>
          </div>
        </div>
      )}
    </>
  );
}
