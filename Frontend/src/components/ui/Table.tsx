import type { KeyboardEvent, ReactNode } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import type { SortOrder } from '../../types/api';
import { Skeleton } from './Skeleton';
import styles from './Table.module.css';

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell(row: T): ReactNode;
  /** When set, the header becomes a sort toggle for this field. */
  sortKey?: string;
  align?: 'left' | 'right';
  width?: number | string;
  nowrap?: boolean;
  /** Hide on narrow screens to keep tables readable. */
  hideBelow?: 'tablet' | 'mobile';
}

export interface SortState {
  key: string;
  order: SortOrder;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  getRowId(row: T): string;
  caption: string;
  loading?: boolean;
  refreshing?: boolean;
  skeletonRows?: number;
  sort?: SortState;
  onSortChange?(sort: SortState): void;
  /** Row activation (click / Enter). Interactive elements inside cells keep their own behaviour. */
  onRowClick?(row: T): void;
  selectedId?: string | null;
  surface?: boolean;
}

function isInteractiveTarget(target: EventTarget | null) {
  return target instanceof HTMLElement && Boolean(target.closest('a, button, input, select, textarea, [role="menu"]'));
}

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  caption,
  loading,
  refreshing,
  skeletonRows = 6,
  sort,
  onSortChange,
  onRowClick,
  selectedId,
  surface,
}: DataTableProps<T>) {
  const cellClass = (column: Column<T>) =>
    [
      column.align === 'right' && styles.right,
      column.nowrap && styles.nowrap,
      column.hideBelow === 'tablet' && styles.hideTablet,
      column.hideBelow === 'mobile' && styles.hideMobile,
    ]
      .filter(Boolean)
      .join(' ') || undefined;

  const renderHeader = (column: Column<T>) => {
    if (!column.sortKey || !onSortChange) return column.header;
    const active = sort?.key === column.sortKey;
    const Icon = !active ? ArrowUpDown : sort?.order === 'asc' ? ArrowUp : ArrowDown;
    return (
      <button
        type="button"
        className={[styles.sortButton, active && styles.sortActive].filter(Boolean).join(' ')}
        onClick={() =>
          onSortChange({
            key: column.sortKey as string,
            order: active && sort?.order === 'desc' ? 'asc' : 'desc',
          })
        }
      >
        {column.header}
        <Icon size={12} className={styles.sortIcon} aria-hidden />
      </button>
    );
  };

  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (!onRowClick || (event.target !== event.currentTarget && isInteractiveTarget(event.target))) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowClick(row);
    }
  };

  return (
    <div
      className={[styles.wrapper, surface && styles.surface, refreshing && styles.refreshing].filter(Boolean).join(' ')}
      aria-busy={loading || refreshing || undefined}
    >
      <table className={styles.table}>
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.id}
                scope="col"
                className={cellClass(column)}
                style={column.width ? { width: column.width } : undefined}
                aria-sort={
                  column.sortKey && sort?.key === column.sortKey ? (sort.order === 'asc' ? 'ascending' : 'descending') : undefined
                }
              >
                {renderHeader(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && !rows
            ? Array.from({ length: skeletonRows }, (_, index) => (
                <tr key={`skeleton-${index}`}>
                  {columns.map((column) => (
                    <td key={column.id} className={cellClass(column)}>
                      <Skeleton width={column.align === 'right' ? '40%' : '70%'} height={14} />
                    </td>
                  ))}
                </tr>
              ))
            : rows?.map((row) => {
                const id = getRowId(row);
                return (
                  <tr
                    key={id}
                    className={[styles.row, onRowClick && styles.interactive, selectedId === id && styles.selected]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={onRowClick ? (event) => !isInteractiveTarget(event.target) && onRowClick(row) : undefined}
                    onKeyDown={onRowClick ? (event) => onRowKeyDown(event, row) : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    aria-current={selectedId === id ? 'true' : undefined}
                  >
                    {columns.map((column) => (
                      <td key={column.id} className={cellClass(column)}>
                        {column.cell(row)}
                      </td>
                    ))}
                  </tr>
                );
              })}
        </tbody>
      </table>
    </div>
  );
}
