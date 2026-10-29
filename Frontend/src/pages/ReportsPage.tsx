import { useState } from 'react';
import { ArrowLeft, ChartNoAxesColumn } from 'lucide-react';
import { Link, useParams } from 'react-router';
import { ReportPreview } from '../components/reports/ReportPreview';
import styles from '../components/reports/Reports.module.css';
import { ButtonLink } from '../components/ui/Button';
import { PageHeader } from '../components/ui/Layout';
import { Pagination } from '../components/ui/Pagination';
import { SearchInput } from '../components/ui/SearchInput';
import { SkeletonBlock } from '../components/ui/Skeleton';
import { EmptyState, ErrorState, NoResultsState } from '../components/ui/StateViews';
import { usePermission } from '../hooks/useAuth';
import { useDebounce } from '../hooks/useDebounce';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { usePagedFilters } from '../hooks/usePagedFilters';
import { useResource } from '../hooks/useResource';
import { reportApi } from '../services/reportApi';
import { formatDate, pluralize } from '../utils/formatting';
import { REPORT_REDACTION_LABELS } from '../utils/labels';
import { FileName } from '../components/ui/FileName';

const PAGE_SIZE = 10;

export default function ReportsPage() {
  useDocumentTitle('Reports');
  const { reportId } = useParams();
  const canUpload = usePermission('documents:upload');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search.trim(), 300);
  const [page, setPage] = usePagedFilters(debouncedSearch);

  const list = useResource(`reports:${debouncedSearch}:${page}`, (signal) =>
    reportApi.list({ search: debouncedSearch || undefined, page, pageSize: PAGE_SIZE }, signal),
  );
  const report = useResource(`report:${reportId ?? ''}`, (signal) => reportApi.get(reportId ?? '', signal), {
    enabled: Boolean(reportId),
  });

  const noReportsAtAll = list.data?.total === 0 && !debouncedSearch;

  return (
    <>
      <PageHeader title="Reports" description="Summaries of each scan, ready to export. Reports never include detected values." />

      {list.status === 'error' && list.error && !list.data ? (
        <ErrorState error={list.error} subject="reports" onRetry={list.reload} />
      ) : noReportsAtAll ? (
        <EmptyState
          icon={ChartNoAxesColumn}
          title="No reports yet"
          description="A report is generated automatically when a scan completes."
          action={
            canUpload && (
              <ButtonLink to="/app/documents/upload" variant="primary">
                Scan a document
              </ButtonLink>
            )
          }
        />
      ) : (
        <div className={[styles.layout, reportId && styles.hasSelection].filter(Boolean).join(' ')}>
          <div className={styles.listColumn}>
            <SearchInput value={search} onChange={setSearch} label="Search reports" placeholder="Search by document" />
            {!list.data ? (
              <SkeletonBlock lines={6} label="Loading reports" />
            ) : list.data.total === 0 ? (
              <NoResultsState onClear={() => setSearch('')} what="reports" />
            ) : (
              <>
                <ul className={styles.list} aria-label="Reports">
                  {list.data.items.map((item) => (
                    <li key={item.id}>
                      <Link
                        to={`/app/reports/${item.id}`}
                        className={[styles.listItem, item.id === reportId && styles.listItemActive].filter(Boolean).join(' ')}
                        aria-current={item.id === reportId ? 'page' : undefined}
                      >
                        <span className={styles.listName}>
                          <FileName name={item.documentName} />
                        </span>
                        <span className={styles.listMeta}>
                          <span>{formatDate(item.generatedAt)}</span>
                          <span aria-hidden>·</span>
                          <span>{pluralize(item.totalFindings, 'finding')}</span>
                          <span aria-hidden>·</span>
                          <span>{REPORT_REDACTION_LABELS[item.redactionStatus]}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
                <Pagination
                  page={list.data.page}
                  pageSize={list.data.pageSize}
                  total={list.data.total}
                  onPageChange={setPage}
                  itemLabel="reports"
                />
              </>
            )}
          </div>

          <div>
            {reportId && (
              <Link to="/app/reports" className={styles.mobileBack}>
                <ArrowLeft size={14} aria-hidden /> All reports
              </Link>
            )}
            {!reportId ? (
              <div className={styles.placeholder}>Select a report to preview it.</div>
            ) : report.status === 'error' && report.error ? (
              <ErrorState error={report.error} subject="this report" onRetry={report.reload} />
            ) : report.data ? (
              <ReportPreview report={report.data} />
            ) : (
              <SkeletonBlock lines={10} label="Loading report" />
            )}
          </div>
        </div>
      )}
    </>
  );
}
