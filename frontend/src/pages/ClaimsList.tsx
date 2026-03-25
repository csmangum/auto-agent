import { useState, useMemo, useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import ClaimTable from '../components/ClaimTable';
import { useClaims } from '../api/queries';

const STATUSES = [
  'pending', 'processing', 'open', 'closed', 'duplicate',
  'fraud_suspected', 'fraud_confirmed', 'needs_review',
  'partial_loss', 'under_investigation', 'denied', 'settled', 'disputed', 'failed', 'archived',
  'purged',
];

const TYPES = [
  'new', 'duplicate', 'total_loss', 'fraud', 'partial_loss',
  'bodily_injury', 'reopened', 'supplemental', 'subrogation',
];

const PAGE_SIZES = [25, 50, 100];

const SORT_OPTIONS = [
  { value: 'created_at', label: 'Date Created' },
  { value: 'incident_date', label: 'Incident Date' },
  { value: 'estimated_damage', label: 'Estimated Damage' },
  { value: 'payout_amount', label: 'Payout Amount' },
  { value: 'status', label: 'Status' },
  { value: 'policy_number', label: 'Policy Number' },
];

const DEFAULT_SORT_BY = 'created_at';
const DEFAULT_SORT_ORDER = 'desc';

const selectClasses =
  'border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-800 text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors';

export default function ClaimsList() {
  const [searchParams, setSearchParams] = useSearchParams();

  // All list controls are URL-synced for shareable / refresh-stable links
  const statusFilter = searchParams.get('status') ?? '';
  const typeFilter = searchParams.get('type') ?? '';
  const includeArchived = searchParams.get('include_archived') === 'true';
  const includePurged = searchParams.get('include_purged') === 'true';
  const search = searchParams.get('search') ?? '';
  const sortBy = searchParams.get('sort_by') ?? DEFAULT_SORT_BY;
  const sortOrder = searchParams.get('sort_order') ?? DEFAULT_SORT_ORDER;
  const page = Math.max(1, Number(searchParams.get('page') ?? '1'));
  const pageSize = Number(searchParams.get('page_size') ?? '25');

  // Local search input state so we can debounce URL updates
  const [searchInput, setSearchInput] = useState(search);

  // Keep local input in sync when URL changes externally (e.g., "Clear filters")
  useEffect(() => {
    setSearchInput(search);
  }, [search]);

  // Debounce: update URL search param 300 ms after user stops typing
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput === search) return; // already in sync – skip URL update
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (searchInput) next.set('search', searchInput);
        else next.delete('search');
        next.delete('page');
        return next;
      }, { replace: true });
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, search, setSearchParams]);

  // Generic helper: update a single URL param and reset page
  const updateParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams);
      if (value) params.set(key, value);
      else params.delete(key);
      params.delete('page');
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const setFilter = useCallback(
    (key: string, value: string) => updateParam(key, value || null),
    [updateParam],
  );

  const setIncludeArchived = useCallback(
    (checked: boolean) => updateParam('include_archived', checked ? 'true' : null),
    [updateParam],
  );

  const setIncludePurged = useCallback(
    (checked: boolean) => updateParam('include_purged', checked ? 'true' : null),
    [updateParam],
  );

  const setPage = useCallback(
    (p: number) => {
      const params = new URLSearchParams(searchParams);
      if (p <= 1) params.delete('page');
      else params.set('page', String(p));
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const hasDataFilters =
    !!(statusFilter || typeFilter || includeArchived || includePurged || search);

  const hasActiveFilters =
    hasDataFilters || sortBy !== DEFAULT_SORT_BY || sortOrder !== DEFAULT_SORT_ORDER;

  const clearAllFilters = useCallback(() => {
    setSearchInput('');
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  const offset = (page - 1) * pageSize;
  const queryParams = {
    limit: pageSize,
    offset,
    sort_by: sortBy,
    sort_order: sortOrder,
    ...(statusFilter && { status: statusFilter }),
    ...(typeFilter && { claim_type: typeFilter }),
    ...(search && { search }),
    ...(includeArchived && { include_archived: true }),
    ...(includePurged && { include_purged: true }),
  };
  const { data, isLoading, error } = useClaims(queryParams);
  const claims = data?.claims ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Generate page numbers for pagination
  const pageNumbers = useMemo(() => {
    const pages: (number | '...')[] = [];
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      if (page > 3) pages.push('...');
      for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) {
        pages.push(i);
      }
      if (page < totalPages - 2) pages.push('...');
      pages.push(totalPages);
    }
    return pages;
  }, [totalPages, page]);

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="Claims"
        subtitle="Browse and filter all claims in the system"
        actions={
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-800 text-gray-400 ring-1 ring-gray-700">
            {total} claim{total !== 1 ? 's' : ''}
          </span>
        }
      />

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 p-4 bg-gray-800/30 rounded-xl border border-gray-700/30">
        {/* Free-text search */}
        <input
          type="search"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search by ID, policy, or VIN…"
          aria-label="Search claims"
          className="border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-800 text-gray-300 placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors min-w-[200px]"
        />

        <label htmlFor="claims-filter-status" className="sr-only">
          Filter by status
        </label>
        <select
          id="claims-filter-status"
          value={statusFilter}
          onChange={(e) => setFilter('status', e.target.value)}
          className={selectClasses}
        >
          <option value="">All Statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        <label htmlFor="claims-filter-type" className="sr-only">
          Filter by claim type
        </label>
        <select
          id="claims-filter-type"
          value={typeFilter}
          onChange={(e) => setFilter('type', e.target.value)}
          className={selectClasses}
        >
          <option value="">All Types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        {/* Sort controls */}
        <select
          value={sortBy}
          onChange={(e) => updateParam('sort_by', e.target.value)}
          className={selectClasses}
          aria-label="Sort by"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={sortOrder}
          onChange={(e) => updateParam('sort_order', e.target.value)}
          className={selectClasses}
          aria-label="Sort order"
        >
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>

        <label htmlFor="claims-page-size" className="sr-only">
          Rows per page
        </label>
        <select
          id="claims-page-size"
          value={pageSize}
          onChange={(e) => {
            const params = new URLSearchParams(searchParams);
            const size = Number(e.target.value);
            if (size === 25) params.delete('page_size');
            else params.set('page_size', String(size));
            params.delete('page');
            setSearchParams(params, { replace: true });
          }}
          className={selectClasses}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size} per page
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
            className="rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500/40"
          />
          <span className="text-sm text-gray-300">Include archived</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includePurged}
            onChange={(e) => setIncludePurged(e.target.checked)}
            className="rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500/40"
          />
          <span className="text-sm text-gray-300">Include purged</span>
        </label>

        {hasActiveFilters && (
          <button
            type="button"
            onClick={clearAllFilters}
            className="text-xs text-gray-400 hover:text-gray-200 px-3 py-2 rounded-lg hover:bg-gray-700 transition-colors"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      )}

      {/* Table */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50">
        {isLoading ? (
          <div className="p-8">
            <div className="space-y-3">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-10 bg-gray-700/30 rounded skeleton-shimmer" />
              ))}
            </div>
          </div>
        ) : (
          <ClaimTable claims={claims} hasFilters={hasDataFilters} />
        )}
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <p className="text-sm text-gray-500">
            Showing {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
          </p>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              aria-label="Previous page"
              className="px-3 py-1.5 text-sm border border-gray-700 rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              ←
            </button>
            {pageNumbers.map((p, i) =>
              p === '...' ? (
                <span key={`ellipsis-${i}`} className="px-2 text-gray-600 text-sm">…</span>
              ) : (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPage(p)}
                  aria-label={`Page ${p}`}
                  aria-current={page === p ? 'page' : undefined}
                  className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                    page === p
                      ? 'bg-blue-600 text-white font-medium'
                      : 'border border-gray-700 bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                  }`}
                >
                  {p}
                </button>
              )
            )}
            <button
              type="button"
              onClick={() => setPage(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages}
              aria-label="Next page"
              className="px-3 py-1.5 text-sm border border-gray-700 rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
