import { useState, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import TypeBadge from '../components/TypeBadge';
import EmptyState from '../components/EmptyState';
import { useReviewQueue, useAssignClaim } from '../api/queries';
import { formatDateTime } from '../utils/date';

const PRIORITIES = ['critical', 'high', 'medium', 'low'] as const;
const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const PAGE_SIZES = [25, 50, 100];

const PRIORITY_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  critical: { bg: 'bg-red-500/20', text: 'text-red-400', icon: '🔴' },
  high: { bg: 'bg-orange-500/20', text: 'text-orange-400', icon: '🟠' },
  medium: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: '🟡' },
  low: { bg: 'bg-gray-500/20', text: 'text-gray-400', icon: '⚪' },
};

const selectClasses =
  'border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-800 text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors';

function timeInQueue(reviewStartedAt?: string): string {
  if (!reviewStartedAt) return '—';
  const start = new Date(reviewStartedAt).getTime();
  const now = Date.now();
  const diffH = Math.floor((now - start) / (1000 * 60 * 60));
  if (diffH < 1) return '<1h';
  if (diffH < 24) return `${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ${diffH % 24}h`;
}

export default function AssignmentQueue() {
  const [priorityFilter, setPriorityFilter] = useState('');
  const [assigneeFilter, setAssigneeFilter] = useState('');
  const [olderThanHours, setOlderThanHours] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [assigningId, setAssigningId] = useState<string | null>(null);
  const [assigneeInput, setAssigneeInput] = useState('');

  const offset = (page - 1) * pageSize;
  const params = {
    limit: pageSize,
    offset,
    ...(priorityFilter && { priority: priorityFilter }),
    ...(assigneeFilter && { assignee: assigneeFilter }),
    ...(olderThanHours && { older_than_hours: Number(olderThanHours) }),
  };

  const { data, isLoading, error } = useReviewQueue(params);
  const assignMutation = useAssignClaim();

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Sort by priority (critical first)
  const sortedClaims = useMemo(() => {
    const claims = data?.claims ?? [];
    return [...claims].sort((a, b) => {
      const pa = PRIORITY_RANK[a.priority ?? 'medium'] ?? 2;
      const pb = PRIORITY_RANK[b.priority ?? 'medium'] ?? 2;
      return pa - pb;
    });
  }, [data?.claims]);

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

  const clearFilters = useCallback(() => {
    setPriorityFilter('');
    setAssigneeFilter('');
    setOlderThanHours('');
    setPage(1);
  }, []);

  const handleAssign = (claimId: string) => {
    if (!assigneeInput.trim()) return;
    assignMutation.mutate(
      { claimId, assignee: assigneeInput.trim() },
      {
        onSuccess: () => {
          setAssigningId(null);
          setAssigneeInput('');
        },
      }
    );
  };

  const hasFilters = !!(priorityFilter || assigneeFilter || olderThanHours);

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="Assignment Queue"
        subtitle="Claims awaiting review — sorted by priority"
        backTo="/workbench"
        backLabel="Workbench"
        actions={
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/15 text-purple-400 ring-1 ring-purple-500/20">
            {total} claim{total !== 1 ? 's' : ''}
          </span>
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap gap-3 p-4 bg-gray-800/30 rounded-xl border border-gray-700/30">
        <select
          value={priorityFilter}
          onChange={(e) => { setPriorityFilter(e.target.value); setPage(1); }}
          className={selectClasses}
        >
          <option value="">All Priorities</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
          ))}
        </select>

        <input
          type="text"
          value={assigneeFilter}
          onChange={(e) => { setAssigneeFilter(e.target.value); setPage(1); }}
          placeholder="Filter by assignee..."
          className={selectClasses + ' w-48'}
        />

        <input
          type="number"
          value={olderThanHours}
          onChange={(e) => { setOlderThanHours(e.target.value); setPage(1); }}
          placeholder="Older than (hours)..."
          min="0"
          step="1"
          className={selectClasses + ' w-48'}
        />

        <select
          value={pageSize}
          onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
          className={selectClasses}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>{size} per page</option>
          ))}
        </select>

        {hasFilters && (
          <button
            type="button"
            onClick={clearFilters}
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
          <div className="p-8 space-y-3">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-10 bg-gray-700/30 rounded skeleton-shimmer" />
            ))}
          </div>
        ) : sortedClaims.length === 0 ? (
          <EmptyState
            icon="✅"
            title="Queue is empty"
            description={hasFilters
              ? 'No claims match your current filters.'
              : 'All claims have been reviewed. Great work!'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50 text-left text-gray-500 text-xs uppercase tracking-wider">
                  <th className="px-4 py-3 font-medium">Priority</th>
                  <th className="px-4 py-3 font-medium">Claim ID</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Assignee</th>
                  <th className="px-4 py-3 font-medium">Time in Queue</th>
                  <th className="px-4 py-3 font-medium">Due</th>
                  <th className="px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {sortedClaims.map((claim) => {
                  const p = claim.priority ?? 'medium';
                  const ps = PRIORITY_STYLES[p] ?? PRIORITY_STYLES.medium;
                  const isAssigning = assigningId === claim.id;

                  return (
                    <tr key={claim.id} className="hover:bg-gray-800/50 transition-colors">
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded ${ps.bg} ${ps.text} capitalize`}>
                          {ps.icon} {p}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <Link to={`/claims/${claim.id}`} className="font-mono text-blue-400 hover:text-blue-300">
                          {claim.id}
                        </Link>
                      </td>
                      <td className="px-4 py-3"><TypeBadge type={claim.claim_type} /></td>
                      <td className="px-4 py-3"><StatusBadge status={claim.status} /></td>
                      <td className="px-4 py-3 text-gray-400">
                        {claim.assignee || <span className="text-gray-600 italic">Unassigned</span>}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs font-mono">
                        {timeInQueue(claim.review_started_at)}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs">
                        {claim.due_at ? formatDateTime(claim.due_at) : '—'}
                      </td>
                      <td className="px-4 py-3">
                        {isAssigning ? (
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={assigneeInput}
                              onChange={(e) => setAssigneeInput(e.target.value)}
                              placeholder="Assignee ID"
                              className="w-28 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                              autoFocus
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleAssign(claim.id);
                                if (e.key === 'Escape') { setAssigningId(null); setAssigneeInput(''); }
                              }}
                            />
                            <button
                              onClick={() => handleAssign(claim.id)}
                              disabled={assignMutation.isPending || !assigneeInput.trim()}
                              className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50 transition-colors"
                            >
                              {assignMutation.isPending ? '…' : '✓'}
                            </button>
                            <button
                              onClick={() => { setAssigningId(null); setAssigneeInput(''); }}
                              className="px-1 py-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
                            >
                              ✕
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => { setAssigningId(claim.id); setAssigneeInput(claim.assignee ?? ''); }}
                            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                          >
                            Assign
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
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
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
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
