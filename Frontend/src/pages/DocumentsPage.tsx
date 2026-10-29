import { useEffect, useMemo, useState } from 'react';
import { FileText, Upload } from 'lucide-react';
import { DocumentsTable } from '../components/documents/DocumentsTable';
import { useDocumentActions } from '../components/documents/useDocumentActions';
import { ButtonLink } from '../components/ui/Button';
import { SelectField } from '../components/ui/Field';
import { FilterBar, PageHeader } from '../components/ui/Layout';
import { Pagination } from '../components/ui/Pagination';
import { SearchInput } from '../components/ui/SearchInput';
import { EmptyState, ErrorState, NoResultsState } from '../components/ui/StateViews';
import type { SortState } from '../components/ui/Table';
import { useAuth } from '../hooks/useAuth';
import { useDebounce } from '../hooks/useDebounce';
import { useDocuments } from '../hooks/useDocuments';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { usePagedFilters } from '../hooks/usePagedFilters';
import type { DocumentFileType, DocumentQuery, DocumentScanStatus, DocumentSortField, DocumentVariant } from '../types/document';
import { DOCUMENT_FILE_TYPES } from '../types/document';
import type { DateRangePreset } from '../utils/dates';
import { DATE_RANGE_OPTIONS, presetToFromDate } from '../utils/dates';
import { DOCUMENT_STATUS_LABELS } from '../utils/labels';

const PAGE_SIZE = 12;
const REFRESH_WHILE_SCANNING_MS = 4000;

export default function DocumentsPage() {
  useDocumentTitle('Documents');
  const { can } = useAuth();
  const [search, setSearch] = useState('');
  const [fileType, setFileType] = useState<DocumentFileType | ''>('');
  const [scanStatus, setScanStatus] = useState<DocumentScanStatus | ''>('');
  const [variant, setVariant] = useState<DocumentVariant | ''>('');
  const [range, setRange] = useState<DateRangePreset>('');
  const [sort, setSort] = useState<SortState>({ key: 'uploadedAt', order: 'desc' });
  const debouncedSearch = useDebounce(search.trim(), 300);
  const [page, setPage] = usePagedFilters(JSON.stringify([debouncedSearch, fileType, scanStatus, variant, range, sort]));

  const query = useMemo<DocumentQuery>(
    () => ({
      search: debouncedSearch || undefined,
      fileType: fileType || undefined,
      scanStatus: scanStatus || undefined,
      variant: variant || undefined,
      uploadedFrom: presetToFromDate(range),
      sortBy: sort.key as DocumentSortField,
      sortOrder: sort.order,
      page,
      pageSize: PAGE_SIZE,
    }),
    [debouncedSearch, fileType, scanStatus, variant, range, sort, page],
  );

  const documents = useDocuments(query);
  const actions = useDocumentActions({ onDeleted: () => documents.reload() });
  const filtered = Boolean(debouncedSearch || fileType || scanStatus || variant || range);

  // Keep statuses current while any listed document is being scanned.
  const { reload } = documents;
  const hasActiveScans = documents.data?.items.some((doc) => doc.scanStatus === 'QUEUED' || doc.scanStatus === 'PROCESSING');
  useEffect(() => {
    if (!hasActiveScans) return;
    const timer = window.setInterval(reload, REFRESH_WHILE_SCANNING_MS);
    return () => window.clearInterval(timer);
  }, [hasActiveScans, reload]);

  const clearFilters = () => {
    setSearch('');
    setFileType('');
    setScanStatus('');
    setVariant('');
    setRange('');
  };

  const uploadAction = can('documents:upload') && (
    <ButtonLink to="/app/documents/upload" variant="primary" icon={<Upload size={16} aria-hidden />}>
      Upload document
    </ButtonLink>
  );

  const data = documents.data;

  return (
    <>
      <PageHeader title="Documents" description="Upload and inspect scanned documents." actions={uploadAction} />

      <FilterBar onClear={clearFilters} canClear={filtered}>
        <SearchInput value={search} onChange={setSearch} label="Search documents" placeholder="Search by file name" />
        <SelectField
          label="Type"
          hideLabel
          value={fileType}
          onChange={setFileType}
          placeholder="All types"
          options={DOCUMENT_FILE_TYPES.map((type) => ({ value: type, label: type }))}
        />
        <SelectField
          label="Scan status"
          hideLabel
          value={scanStatus}
          onChange={setScanStatus}
          placeholder="All statuses"
          options={(Object.keys(DOCUMENT_STATUS_LABELS) as DocumentScanStatus[]).map((status) => ({
            value: status,
            label: DOCUMENT_STATUS_LABELS[status],
          }))}
        />
        <SelectField
          label="Version"
          hideLabel
          value={variant}
          onChange={setVariant}
          placeholder="Originals and copies"
          options={[
            { value: 'ORIGINAL', label: 'Originals only' },
            { value: 'SANITIZED', label: 'Sanitized copies' },
          ]}
        />
        <SelectField
          label="Uploaded"
          hideLabel
          value={range}
          onChange={setRange}
          placeholder="Any time"
          options={DATE_RANGE_OPTIONS}
        />
      </FilterBar>

      {documents.status === 'error' && documents.error ? (
        <ErrorState error={documents.error} subject="documents" onRetry={documents.reload} />
      ) : data && data.total === 0 ? (
        filtered ? (
          <NoResultsState onClear={clearFilters} what="documents" />
        ) : (
          <EmptyState
            icon={FileText}
            title="No documents yet"
            description="Upload your first document to begin scanning."
            action={uploadAction}
          />
        )
      ) : (
        <>
          <DocumentsTable
            documents={data?.items}
            loading={documents.status === 'loading'}
            refreshing={documents.isRefreshing}
            sort={sort}
            onSortChange={setSort}
            onScan={(document) => void actions.startScan(document)}
            onDownload={actions.download}
            onDelete={actions.requestDelete}
            scanningId={actions.scanningId}
          />
          {data && (
            <Pagination
              page={data.page}
              pageSize={data.pageSize}
              total={data.total}
              onPageChange={setPage}
              itemLabel="documents"
            />
          )}
        </>
      )}
      {actions.dialogs}
    </>
  );
}
