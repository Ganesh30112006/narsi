import { ChevronLeft, ChevronRight } from 'lucide-react';
import { formatNumber } from '../../utils/formatting';
import { IconButton } from './Button';
import styles from './Misc.module.css';

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange(page: number): void;
  itemLabel?: string;
}

export function Pagination({ page, pageSize, total, onPageChange, itemLabel = 'results' }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);

  return (
    <nav className={styles.pagination} aria-label="Pagination">
      <span className={styles.paginationSummary} aria-live="polite">
        {formatNumber(start)}–{formatNumber(end)} of {formatNumber(total)} {itemLabel}
      </span>
      {pageCount > 1 && (
        <div className={styles.paginationControls}>
          <IconButton label="Previous page" size="sm" bordered disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
            <ChevronLeft size={16} aria-hidden />
          </IconButton>
          <span className={styles.paginationPage}>
            Page {page} of {pageCount}
          </span>
          <IconButton label="Next page" size="sm" bordered disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>
            <ChevronRight size={16} aria-hidden />
          </IconButton>
        </div>
      )}
    </nav>
  );
}
