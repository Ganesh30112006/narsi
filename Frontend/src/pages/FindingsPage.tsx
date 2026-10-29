import { useMemo, useState } from 'react';
import { ListChecks } from 'lucide-react';
import { useSearchParams } from 'react-router';
import { FindingDrawer } from '../components/findings/FindingDrawer';
import { FindingsTable } from '../components/findings/FindingsTable';
import { ButtonLink } from '../components/ui/Button';
import { SelectField } from '../components/ui/Field';
import { FilterBar, PageHeader } from '../components/ui/Layout';
import { Pagination } from '../components/ui/Pagination';
import { SearchInput } from '../components/ui/SearchInput';
import { EmptyState, ErrorState, NoResultsState } from '../components/ui/StateViews';
import type { SortState } from '../components/ui/Table';
import { usePermission } from '../hooks/useAuth';
import { useDebounce } from '../hooks/useDebounce';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useFindings } from '../hooks/useFindings';
import { usePagedFilters } from '../hooks/usePagedFilters';
import { useResource } from '../hooks/useResource';
import { documentApi } from '../services/documentApi';
import type { ConfidenceLevel, DetectionMethod, Finding, FindingQuery, FindingSortField, PIIType } from '../types/finding';
import { DETECTION_METHODS, PII_TYPES } from '../types/finding';
import type { DateRangePreset } from '../utils/dates';
import { DATE_RANGE_OPTIONS, presetToFromDate } from '../utils/dates';
import { CONFIDENCE_LABELS, DETECTION_METHOD_LABELS, PII_TYPE_LABELS } from '../utils/labels';

const PAGE_SIZE = 15;

export default function FindingsPage() {
  useDocumentTitle('Findings');
  const canUpload = usePermission('documents:upload');
  const [params, setParams] = useSearchParams();
  const documentId = params.get('documentId') ?? '';
  const [search, setSearch] = useState('');
  const [piiType, setPiiType] = useState<PIIType | ''>('');
  const [confidence, setConfidence] = useState<ConfidenceLevel | ''>('');
  const [method, setMethod] = useState<DetectionMethod | ''>('');
  const [range, setRange] = useState<DateRangePreset>('');
  const [sort, setSort] = useState<SortState>({ key: 'confidence', order: 'desc' });
  const [selected, setSelected] = useState<Finding | null>(null);
  const debouncedSearch = useDebounce(search.trim(), 300);
  const [page, setPage] = usePagedFilters(
    JSON.stringify([debouncedSearch, piiType, confidence, method, range, documentId, sort]),
  );

  const scannedDocuments = useResource(
    'findings:document-options',
    (signal) =>
      documentApi.list(
        { scanStatus: 'COMPLETED', variant: 'ORIGINAL', pageSize: 100, sortBy: 'fileName', sortOrder: 'asc' },
        signal,
      ),
    { staleTimeMs: 30_000 },
  );

  const query = useMemo<FindingQuery>(
    () => ({
      search: debouncedSearch || undefined,
      piiType: piiType || undefined,
      confidenceLevel: confidence || undefined,
      detectionMethod: method || undefined,
      documentId: documentId || undefined,
      createdFrom: presetToFromDate(range),
      sortBy: sort.key as FindingSortField,
      sortOrder: sort.order,
      page,
      pageSize: PAGE_SIZE,
    }),
    [debouncedSearch, piiType, confidence, method, documentId, range, sort, page],
  );
  const findings = useFindings(query);
  const filtered = Boolean(debouncedSearch || piiType || confidence || method || range || documentId);

  const setDocumentId = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set('documentId', value);
    else next.delete('documentId');
    setParams(next, { replace: true });
  };

  const clearFilters = () => {
    setSearch('');
    setPiiType('');
    setConfidence('');
    setMethod('');
    setRange('');
    setDocumentId('');
  };

  const data = findings.data;

  return (
    <>
      <PageHeader title="Findings" description="Every detected identifier across your scanned documents. Values are masked." />

      <FilterBar onClear={clearFilters} canClear={filtered}>
        <SearchInput value={search} onChange={setSearch} label="Search findings" placeholder="Search by document or type" />
        <SelectField
          label="PII type"
          hideLabel
          value={piiType}
          onChange={setPiiType}
          placeholder="All PII types"
          options={PII_TYPES.map((type) => ({ value: type, label: PII_TYPE_LABELS[type] }))}
        />
        <SelectField
          label="Confidence"
          hideLabel
          value={confidence}
          onChange={setConfidence}
          placeholder="Any confidence"
          options={(['HIGH', 'MEDIUM', 'LOW'] as const).map((level) => ({ value: level, label: CONFIDENCE_LABELS[level] }))}
        />
        <SelectField
          label="Detection method"
          hideLabel
          value={method}
          onChange={setMethod}
          placeholder="Any method"
          options={DETECTION_METHODS.map((value) => ({ value, label: DETECTION_METHOD_LABELS[value] }))}
        />
        <SelectField
          label="Document"
          hideLabel
          value={documentId}
          onChange={setDocumentId}
          placeholder={scannedDocuments.status === 'error' ? 'Documents unavailable' : 'All documents'}
          options={(scannedDocuments.data?.items ?? []).map((document) => ({ value: document.id, label: document.fileName }))}
        />
        <SelectField
          label="Detected"
          hideLabel
          value={range}
          onChange={setRange}
          placeholder="Any time"
          options={DATE_RANGE_OPTIONS}
        />
      </FilterBar>

      {findings.status === 'error' && findings.error ? (
        <ErrorState error={findings.error} subject="findings" onRetry={findings.reload} />
      ) : data && data.total === 0 ? (
        filtered ? (
          <NoResultsState onClear={clearFilters} what="findings" />
        ) : (
          <EmptyState
            icon={ListChecks}
            title="No findings yet"
            description="Findings appear here after documents are scanned."
            action={
              canUpload && (
                <ButtonLink to="/app/documents/upload" variant="primary">
                  Scan a document
                </ButtonLink>
              )
            }
          />
        )
      ) : (
        <>
          <FindingsTable
            findings={data?.items}
            loading={findings.status === 'loading'}
            refreshing={findings.isRefreshing}
            sort={sort}
            onSortChange={setSort}
            onSelect={setSelected}
            selectedId={selected?.id}
          />
          {data && (
            <Pagination
              page={data.page}
              pageSize={data.pageSize}
              total={data.total}
              onPageChange={setPage}
              itemLabel="findings"
            />
          )}
        </>
      )}

      <FindingDrawer finding={selected} onClose={() => setSelected(null)} />
    </>
  );
}
