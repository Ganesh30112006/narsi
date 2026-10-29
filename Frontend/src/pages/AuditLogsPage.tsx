import { useMemo, useState } from 'react';
import { ScrollText } from 'lucide-react';
import { AuditTable } from '../components/audit/AuditTable';
import { SelectField } from '../components/ui/Field';
import { FilterBar, PageHeader } from '../components/ui/Layout';
import { Pagination } from '../components/ui/Pagination';
import { SearchInput } from '../components/ui/SearchInput';
import { EmptyState, ErrorState, NoResultsState } from '../components/ui/StateViews';
import { useDebounce } from '../hooks/useDebounce';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { usePagedFilters } from '../hooks/usePagedFilters';
import { useResource } from '../hooks/useResource';
import { auditApi } from '../services/auditApi';
import type { AuditAction, AuditQuery, AuditResult } from '../types/audit';
import { AUDIT_ACTIONS } from '../types/audit';
import type { DateRangePreset } from '../utils/dates';
import { DATE_RANGE_OPTIONS, presetToFromDate } from '../utils/dates';
import { AUDIT_ACTION_LABELS, AUDIT_RESULT_LABELS } from '../utils/labels';

const PAGE_SIZE = 20;

export default function AuditLogsPage() {
  useDocumentTitle('Audit logs');
  const [search, setSearch] = useState('');
  const [action, setAction] = useState<AuditAction | ''>('');
  const [result, setResult] = useState<AuditResult | ''>('');
  const [range, setRange] = useState<DateRangePreset>('');
  const debouncedSearch = useDebounce(search.trim(), 300);
  const [page, setPage] = usePagedFilters(JSON.stringify([debouncedSearch, action, result, range]));

  const query = useMemo<AuditQuery>(
    () => ({
      search: debouncedSearch || undefined,
      action: action || undefined,
      result: result || undefined,
      from: presetToFromDate(range),
      page,
      pageSize: PAGE_SIZE,
    }),
    [debouncedSearch, action, result, range, page],
  );
  const logs = useResource(`audit:${JSON.stringify(query)}`, (signal) => auditApi.list(query, signal));
  const filtered = Boolean(debouncedSearch || action || result || range);

  const clearFilters = () => {
    setSearch('');
    setAction('');
    setResult('');
    setRange('');
  };

  return (
    <>
      <PageHeader
        title="Audit logs"
        description="A record of who accessed or changed documents and findings. Sensitive values are never logged."
      />

      <FilterBar onClear={clearFilters} canClear={filtered}>
        <SearchInput
          value={search}
          onChange={setSearch}
          label="Search audit logs"
          placeholder="Search by user, action or document"
        />
        <SelectField
          label="Action"
          hideLabel
          value={action}
          onChange={setAction}
          placeholder="All actions"
          options={AUDIT_ACTIONS.map((value) => ({ value, label: AUDIT_ACTION_LABELS[value] }))}
        />
        <SelectField
          label="Result"
          hideLabel
          value={result}
          onChange={setResult}
          placeholder="All results"
          options={(['SUCCESS', 'FAILURE', 'DENIED'] as const).map((value) => ({ value, label: AUDIT_RESULT_LABELS[value] }))}
        />
        <SelectField
          label="Date"
          hideLabel
          value={range}
          onChange={setRange}
          placeholder="Any time"
          options={DATE_RANGE_OPTIONS}
        />
      </FilterBar>

      {logs.status === 'error' && logs.error ? (
        <ErrorState error={logs.error} subject="audit logs" onRetry={logs.reload} />
      ) : logs.data && logs.data.total === 0 ? (
        filtered ? (
          <NoResultsState onClear={clearFilters} what="entries" />
        ) : (
          <EmptyState
            icon={ScrollText}
            title="No audit entries yet"
            description="Activity will be recorded here as people use GovPII Guard."
          />
        )
      ) : (
        <>
          <AuditTable entries={logs.data?.items} loading={logs.status === 'loading'} refreshing={logs.isRefreshing} />
          {logs.data && (
            <Pagination
              page={logs.data.page}
              pageSize={logs.data.pageSize}
              total={logs.data.total}
              onPageChange={setPage}
              itemLabel="entries"
            />
          )}
        </>
      )}
    </>
  );
}
