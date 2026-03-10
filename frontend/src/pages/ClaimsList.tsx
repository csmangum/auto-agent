import { useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import ClaimTable from '../components/ClaimTable';
import { useClaims } from '../api/queries';

const STATUSES = [
  'pending', 'processing', 'open', 'closed', 'duplicate',
  'fraud_suspected', 'fraud_confirmed', 'needs_review',
  'partial_loss', 'under_investigation', 'denied', 'settled', 'disputed', 'failed',
];

const TYPES = ['new', 'duplicate', 'total_loss', 'fraud', 'partial_loss'];

const PAGE_SIZES = [25, 50, 100];

const selectClasses =
  'border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-800 text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors';

export default function ClaimsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const statusFilter = searchParams.get('status') ?? '';
  const [typeFilter, setTypeFilter] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const setStatusFilter = (value: string) => {
    const params = new URLSearchParams(searchParams);
    if (value) {
      params.set('status', value);
    } else {
      params.delete('status');
    }
    setSearchParams(params, { replace: true });
    setPage(1);
  };

  const offset = (page - 1) * pageSize;
  const params = {
    limit: pageSize,
    offset,
    ...(statusFilter && { status: statusFilter }),
    ...(typeFilter && { claim_type: typeFilter }),
  };
  const { data, isLoading, error } = useClaims(params);
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
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={selectClasses}
        >
          <option value="">All Statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
          className={selectClasses}
        >
          <option value="">All Types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        <select
          value={pageSize}
          onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
          className={selectClasses}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size} per page
            </option>
          ))}
        </select>

        {(statusFilter || typeFilter) && (
          <button
            type="button"
            onClick={() => { setStatusFilter(''); setTypeFilter(''); }}
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
          <ClaimTable claims={claims} hasFilters={!!(statusFilter || typeFilter)} />
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
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
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
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
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
