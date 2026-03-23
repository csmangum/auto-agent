import { Suspense, lazy } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';
import ClaimTable from '../components/ClaimTable';
import FraudComplianceSection from '../components/FraudComplianceSection';
import { useClaimsStats, useClaims } from '../api/queries';

const DashboardCharts = lazy(() => import('../components/DashboardCharts'));

const TYPE_COLORS: Record<string, string> = {
  new: '#3B82F6',
  duplicate: '#F97316',
  total_loss: '#6366F1',
  fraud: '#EF4444',
  partial_loss: '#14B8A6',
  unclassified: '#6B7280',
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
  unknown: '#6B7280',
};

const QUICK_ACTIONS = [
  { to: '/claims/new', label: 'New Claim', icon: '➕' },
  { to: '/workbench', label: 'My Workbench', icon: '🗂️' },
  { to: '/workbench/queue', label: 'Review Queue', icon: '👁️' },
  { to: '/system', label: 'System Health', icon: '⚙️' },
];

export default function Dashboard() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useClaimsStats();
  const { data: claimsData, isLoading: claimsLoading, error: claimsError } = useClaims({ limit: 10 });
  const loading = statsLoading || claimsLoading;
  const error = statsError ?? claimsError;

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Dashboard" subtitle="Claims system overview" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 stagger">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
              <div className="h-4 bg-gray-700/50 rounded w-24 mb-3 skeleton-shimmer" />
              <div className="h-8 bg-gray-700/50 rounded w-16 skeleton-shimmer" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Dashboard" subtitle="Claims system overview" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <div>
            <p className="text-sm font-medium text-red-400">Error loading dashboard</p>
            <p className="text-sm text-red-400/70 mt-0.5">{error instanceof Error ? error.message : 'Unknown error'}</p>
          </div>
        </div>
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
    <div className="space-y-6 animate-fade-in">
      <PageHeader title="Dashboard" subtitle="Claims system overview" />

      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 stagger">
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

      {/* Quick actions */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {QUICK_ACTIONS.map((action) => (
          <Link
            key={action.to}
            to={action.to}
            className="flex items-center gap-2.5 px-4 py-3 rounded-lg bg-gray-800/50 border border-gray-700/50 text-sm text-gray-300 hover:bg-gray-800 hover:text-gray-100 hover:border-gray-600 transition-all group"
          >
            <span className="text-base group-hover:scale-110 transition-transform">{action.icon}</span>
            {action.label}
          </Link>
        ))}
      </div>

      {/* Charts */}
      <Suspense
        fallback={
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5 h-[340px] skeleton-shimmer" />
            <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5 h-[340px] skeleton-shimmer" />
          </div>
        }
      >
        <DashboardCharts typeData={typeData} statusData={statusData} />
      </Suspense>

      {/* Fraud compliance */}
      <FraudComplianceSection />

      {/* Recent claims */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-300">Recent Claims</h3>
          <Link
            to="/claims"
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            View all →
          </Link>
        </div>
        <ClaimTable claims={claimsData?.claims ?? []} compact />
      </div>
    </div>
  );
}
