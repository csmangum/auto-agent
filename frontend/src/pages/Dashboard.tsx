import { Suspense, lazy } from 'react';
import StatCard from '../components/StatCard';
import ClaimTable from '../components/ClaimTable';
import { useClaimsStats, useClaims } from '../api/queries';

const DashboardCharts = lazy(() => import('../components/DashboardCharts'));

const TYPE_COLORS: Record<string, string> = {
  new: '#3B82F6',
  duplicate: '#F97316',
  total_loss: '#6366F1',
  fraud: '#EF4444',
  partial_loss: '#14B8A6',
  unclassified: '#9CA3AF',
};

const STATUS_COLORS: Record<string, string> = {
  pending: '#EAB308',
  processing: '#3B82F6',
  open: '#22C55E',
  closed: '#6B7280',
  duplicate: '#F97316',
  fraud_suspected: '#EF4444',
  fraud_confirmed: '#DC2626',
  needs_review: '#A855F7',
  partial_loss: '#14B8A6',
  under_investigation: '#D97706',
  denied: '#B91C1C',
  settled: '#059669',
  disputed: '#EC4899',
  failed: '#991B1B',
  unknown: '#9CA3AF',
};

export default function Dashboard() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useClaimsStats();
  const { data: claimsData, isLoading: claimsLoading, error: claimsError } = useClaims({ limit: 10 });
  const loading = statsLoading || claimsLoading;
  const error = statsError ?? claimsError;

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-5 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-24 mb-3" />
              <div className="h-8 bg-gray-200 rounded w-16" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-800">Error loading dashboard: {error instanceof Error ? error.message : 'Unknown error'}</p>
      </div>
    );
  }

  if (!stats) return null;

  const typeData = Object.entries(stats.by_type ?? {}).map(([name, value]) => ({
    name: name.replace(/_/g, ' '),
    value,
    fill: TYPE_COLORS[name] ?? TYPE_COLORS.unclassified,
  }));

  const statusData = Object.entries(stats.by_status ?? {}).map(([name, value]) => ({
    name: name.replace(/_/g, ' '),
    value,
    fill: STATUS_COLORS[name] ?? STATUS_COLORS.unknown,
  }));

  const activeStatuses = ['pending', 'processing', 'needs_review', 'under_investigation'];
  const activeCount = activeStatuses.reduce(
    (sum, s) => sum + (stats.by_status?.[s] ?? 0),
    0
  );
  const resolvedStatuses = ['closed', 'settled', 'denied', 'duplicate'];
  const resolvedCount = resolvedStatuses.reduce(
    (sum, s) => sum + (stats.by_status?.[s] ?? 0),
    0
  );
  const flaggedStatuses = ['fraud_suspected', 'fraud_confirmed', 'disputed'];
  const flaggedCount = flaggedStatuses.reduce(
    (sum, s) => sum + (stats.by_status?.[s] ?? 0),
    0
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Claims system observability overview</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Claims"
          value={stats.total_claims}
          subtitle={`${stats.total_audit_events} audit events`}
          icon="📋"
          color="blue"
        />
        <StatCard
          title="Active"
          value={activeCount}
          subtitle="Pending, processing, review"
          icon="⏳"
          color="orange"
        />
        <StatCard
          title="Resolved"
          value={resolvedCount}
          subtitle="Closed, settled, denied"
          icon="✅"
          color="green"
        />
        <StatCard
          title="Flagged"
          value={flaggedCount}
          subtitle="Fraud, disputed"
          icon="🚩"
          color="red"
        />
      </div>

      <Suspense
        fallback={
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white rounded-xl border border-gray-200 p-5 h-[340px] animate-pulse" />
            <div className="bg-white rounded-xl border border-gray-200 p-5 h-[340px] animate-pulse" />
          </div>
        }
      >
        <DashboardCharts typeData={typeData} statusData={statusData} />
      </Suspense>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">Recent Claims</h3>
        <ClaimTable claims={claimsData?.claims ?? []} compact />
      </div>
    </div>
  );
}
