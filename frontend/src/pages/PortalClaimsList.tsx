import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useInfiniteQuery } from '@tanstack/react-query';
import { portalApi } from '../api/portalClient';
import StatusBadge from '../components/StatusBadge';
import EmptyState from '../components/EmptyState';
import { formatDateTime } from '../utils/date';
import { usePortal } from '../context/usePortal';

const PAGE_SIZE = 50;

export default function PortalClaimsList() {
  const navigate = useNavigate();
  const { logout, session } = usePortal();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const sessionKey =
    session?.token ??
    (session?.policyNumber && session?.vin
      ? `${session.policyNumber}:${session.vin}`
      : null) ??
    session?.email ??
    '';

  const {
    data,
    isLoading,
    error,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery({
    queryKey: ['portal', 'claims', sessionKey],
    queryFn: ({ pageParam }) =>
      portalApi.getClaims({ limit: PAGE_SIZE, offset: pageParam as number }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const batch = lastPage.claims?.length ?? 0;
      if (batch < PAGE_SIZE) return undefined;
      const loaded = allPages.reduce((sum, p) => sum + (p.claims?.length ?? 0), 0);
      if (loaded >= (lastPage.total ?? 0)) return undefined;
      return loaded;
    },
  });

  const totalFromApi = data?.pages[0]?.total ?? 0;

  const rawClaims = useMemo(
    () =>
      (data?.pages.flatMap((p) => p.claims ?? []) ?? []) as Array<{
        id: string;
        status: string;
        claim_type?: string;
        vehicle_year?: number;
        vehicle_make?: string;
        vehicle_model?: string;
        incident_description?: string;
        estimated_damage?: number;
        payout_amount?: number;
        created_at?: string;
      }>,
    [data?.pages]
  );

  const filteredClaims = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rawClaims.filter((c) => {
      if (statusFilter && (c.status ?? '').toLowerCase() !== statusFilter.toLowerCase()) {
        return false;
      }
      if (q && !c.id.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [rawClaims, search, statusFilter]);

  const statusOptions = useMemo(() => {
    const set = new Set<string>();
    for (const c of rawClaims) {
      if (c.status) set.add(c.status);
    }
    return [...set].sort();
  }, [rawClaims]);

  const showLoadMore = !!hasNextPage && !search && !statusFilter;

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-gray-800 bg-gray-900/50 px-4 py-3 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-100">My Claims</h1>
        <button
          type="button"
          onClick={logout}
          className="text-sm text-gray-400 hover:text-gray-200 transition-colors"
        >
          Sign Out
        </button>
      </header>

      <main className="p-4 max-w-2xl mx-auto">
        {error && (
          <div className="mb-4 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error instanceof Error ? error.message : 'Failed to load claims'}
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <label className="flex-1 min-w-0">
            <span className="sr-only">Search by claim ID</span>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by claim ID…"
              className="w-full bg-gray-800/80 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
            />
          </label>
          <label className="sm:w-44 shrink-0">
            <span className="sr-only">Filter by status</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full bg-gray-800/80 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
            >
              <option value="">All statuses</option>
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </label>
        </div>

        {totalFromApi > 0 && (
          <p className="text-xs text-gray-500 mb-3">
            Showing {filteredClaims.length} of {rawClaims.length} loaded
            {totalFromApi > rawClaims.length ? ` (${totalFromApi} total from server)` : ''}
            .
            {search || statusFilter ? ' Clear filters to load more pages.' : null}
          </p>
        )}

        {isLoading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div
                key={i}
                className="h-20 bg-gray-800/50 rounded-xl animate-pulse"
              />
            ))}
          </div>
        ) : filteredClaims.length === 0 ? (
          <EmptyState
            icon="📋"
            title={rawClaims.length === 0 ? 'No claims found' : 'No matching claims'}
            description={
              rawClaims.length === 0
                ? "We couldn't find any claims matching your information."
                : 'Try a different search or status filter.'
            }
          />
        ) : (
          <>
            <div className="space-y-3">
              {filteredClaims.map((claim) => (
                <button
                  key={claim.id}
                  type="button"
                  onClick={() => navigate(`/portal/claims/${claim.id}`)}
                  className="w-full text-left bg-gray-800/50 rounded-xl border border-gray-700/50 p-4 hover:bg-gray-800/70 hover:border-emerald-500/20 transition-all group"
                >
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="flex items-center gap-3 min-w-0">
                      <p className="text-sm font-semibold text-gray-200 group-hover:text-emerald-400 transition-colors truncate font-mono">
                        {claim.id}
                      </p>
                      <StatusBadge status={claim.status} />
                    </div>
                    <span className="text-xs text-gray-500 shrink-0">
                      {formatDateTime(claim.created_at) ?? '—'}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-gray-400">
                    <span>
                      {claim.vehicle_year} {claim.vehicle_make}{' '}
                      {claim.vehicle_model}
                    </span>
                    {claim.estimated_damage != null && (
                      <span className="text-gray-500">
                        Est. $
                        {Number(claim.estimated_damage).toLocaleString()}
                      </span>
                    )}
                    {claim.payout_amount != null && (
                      <span className="text-emerald-400 font-medium">
                        Payout: $
                        {Number(claim.payout_amount).toLocaleString()}
                      </span>
                    )}
                  </div>
                  {claim.incident_description && (
                    <p className="text-xs text-gray-500 mt-2 line-clamp-1">
                      {claim.incident_description}
                    </p>
                  )}
                </button>
              ))}
            </div>
            {showLoadMore && (
              <div className="mt-4 flex justify-center">
                <button
                  type="button"
                  disabled={isFetchingNextPage}
                  onClick={() => void fetchNextPage()}
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-600/30 disabled:opacity-50 transition-colors"
                >
                  {isFetchingNextPage ? 'Loading…' : 'Load more'}
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
