import { useState, useEffect } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import StatCard from '../components/StatCard';
import ClaimTable from '../components/ClaimTable';
import { getClaimsStats, getClaims } from '../api/client';
import type { Claim, ClaimsStats } from '../api/types';

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
  const [stats, setStats] = useState<ClaimsStats | null>(null);
  const [recentClaims, setRecentClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getClaimsStats(), getClaims({ limit: 10 })])
      .then(([statsData, claimsData]) => {
        setStats(statsData);
        setRecentClaims(claimsData.claims);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unknown error'))
      .finally(() => setLoading(false));
  }, []);

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
        <p className="text-red-800">Error loading dashboard: {error}</p>
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Claims by Type</h3>
          {typeData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={typeData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={2}
                  dataKey="value"
                  label={({ name, value }) => `${name} (${value})`}
                >
                  {typeData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-sm py-8 text-center">No data</p>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Claims by Status</h3>
          {statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={statusData} layout="vertical" margin={{ left: 80 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={80} />
                <Tooltip />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {statusData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-sm py-8 text-center">No data</p>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">Recent Claims</h3>
        <ClaimTable claims={recentClaims} compact />
      </div>
    </div>
  );
}
