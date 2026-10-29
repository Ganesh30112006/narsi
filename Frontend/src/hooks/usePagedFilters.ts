import { useCallback, useState } from 'react';

/**
 * Page number that automatically returns to 1 whenever `filterKey` changes —
 * derived during render, so no extra request is fired for the stale page.
 */
export function usePagedFilters(filterKey: string): [number, (page: number) => void] {
  const [state, setState] = useState({ key: filterKey, page: 1 });
  const page = state.key === filterKey ? state.page : 1;
  const setPage = useCallback((next: number) => setState({ key: filterKey, page: next }), [filterKey]);
  return [page, setPage];
}
