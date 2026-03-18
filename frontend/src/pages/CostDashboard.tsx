import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';
import { useCostBreakdown } from '../api/queries';
import type { CostBreakdown } from '../api/client';

const CREW_COLORS: Record<string, string> = {
  router: '#3B82F6',
  escalation: '#F97316',
  partial_loss: '#14B8A6',
  total_loss: '#6366F1',
  new: '#22C55E',
  duplicate: '#F59E0B',
  fraud: '#EF4444',
  bodily_injury: '#8B5CF6',
  reopened: '#6B7280',
  task_planner: '#0EA5E9',
  rental: '#EAB308',
  liability_determination: '#EC4899',
  settlement: '#059669',
  subrogation: '#D946EF',
  salvage: '#78716C',
  after_action: '#64748B',
  residual: '#94A3B8',
};

function formatCost(usd: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(usd);
}

function formatTokens(n: number) {
  return new Intl.NumberFormat('en-US').format(n);
}

function CrewTable({ byCrew }: { byCrew: Record<string, { total_cost_usd: number; total_tokens: number; total_calls: number }> }) {
  const entries = Object.entries(byCrew ?? {}).sort(
    (a, b) => b[1].total_cost_usd - a[1].total_cost_usd
  );
  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500 py-4">No crew usage data yet. Process claims to see cost attribution.</p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700/50 text-left text-xs uppercase tracking-wider text-gray-500">
            <th className="px-4 py-2 font-medium">Crew</th>
            <th className="px-4 py-2 font-medium text-right">Cost</th>
            <th className="px-4 py-2 font-medium text-right">Tokens</th>
            <th className="px-4 py-2 font-medium text-right">Calls</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700/30">
          {entries.map(([crew, data]) => (
            <tr key={crew} className="hover:bg-gray-800/80 transition-colors">
              <td className="px-4 py-2.5">
                <span
                  className="inline-block w-2 h-2 rounded-full mr-2"
                  style={{ backgroundColor: CREW_COLORS[crew] ?? '#6B7280' }}
                />
                {crew.replace(/_/g, ' ')}
              </td>
              <td className="px-4 py-2.5 text-right font-mono text-blue-400">{formatCost(data.total_cost_usd)}</td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-400">{formatTokens(data.total_tokens)}</td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-400">{data.total_calls}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClaimTypeTable({ byClaimType }: { byClaimType: Record<string, { total_cost_usd: number; total_tokens: number; total_claims: number; total_calls: number }> }) {
  const entries = Object.entries(byClaimType ?? {}).sort(
    (a, b) => b[1].total_cost_usd - a[1].total_cost_usd
  );
  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500 py-4">No claim-type data yet.</p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700/50 text-left text-xs uppercase tracking-wider text-gray-500">
            <th className="px-4 py-2 font-medium">Claim Type</th>
            <th className="px-4 py-2 font-medium text-right">Cost</th>
            <th className="px-4 py-2 font-medium text-right">Tokens</th>
            <th className="px-4 py-2 font-medium text-right">Claims</th>
            <th className="px-4 py-2 font-medium text-right">Calls</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700/30">
          {entries.map(([type, data]) => (
            <tr key={type} className="hover:bg-gray-800/80 transition-colors">
              <td className="px-4 py-2.5">{type.replace(/_/g, ' ')}</td>
              <td className="px-4 py-2.5 text-right font-mono text-blue-400">{formatCost(data.total_cost_usd)}</td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-400">{formatTokens(data.total_tokens)}</td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-400">{data.total_claims}</td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-400">{data.total_calls}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DailyTable({ daily }: { daily: Record<string, { total_cost_usd: number; total_tokens: number; claims: number }> }) {
  const entries = Object.entries(daily ?? {}).sort((a, b) => b[0].localeCompare(a[0])).slice(0, 14);
  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500 py-4">No daily data yet.</p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700/50 text-left text-xs uppercase tracking-wider text-gray-500">
            <th className="px-4 py-2 font-medium">Date</th>
            <th className="px-4 py-2 font-medium text-right">Cost</th>
            <th className="px-4 py-2 font-medium text-right">Tokens</th>
            <th className="px-4 py-2 font-medium text-right">Claims</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700/30">
          {entries.map(([date, data]) => (
            <tr key={date} className="hover:bg-gray-800/80 transition-colors">
              <td className="px-4 py-2.5 font-mono text-gray-400">{date}</td>
              <td className="px-4 py-2.5 text-right font-mono text-blue-400">{formatCost(data.total_cost_usd)}</td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-400">{formatTokens(data.total_tokens)}</td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-400">{data.claims}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CostDashboard() {
  const { data, isLoading, error } = useCostBreakdown();

  if (isLoading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="LLM Cost Dashboard" subtitle="Token and cost attribution by crew and claim type" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
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
        <PageHeader title="LLM Cost Dashboard" subtitle="Token and cost attribution by crew and claim type" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <div>
            <p className="text-sm font-medium text-red-400">Error loading cost data</p>
            <p className="text-sm text-red-400/70 mt-0.5">{error instanceof Error ? error.message : 'Unknown error'}</p>
          </div>
        </div>
      </div>
    );
  }

  const cost = data as CostBreakdown | undefined;
  const gs = cost?.global_stats ?? {};
  const byCrew = cost?.by_crew ?? {};
  const byClaimType = cost?.by_claim_type ?? {};
  const daily = cost?.daily ?? {};

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="LLM Cost Dashboard"
        subtitle="Token and cost attribution by crew, claim type, and daily spend"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Cost"
          value={formatCost(cost?.total_cost_usd ?? 0)}
          subtitle="All claims (session)"
          icon="💰"
          color="blue"
        />
        <StatCard
          title="Total Tokens"
          value={formatTokens(cost?.total_tokens ?? 0)}
          subtitle="Input + output"
          icon="📊"
          color="green"
        />
        <StatCard
          title="Claims Processed"
          value={gs.total_claims ?? 0}
          subtitle="In current session"
          icon="📋"
          color="orange"
        />
        <StatCard
          title="Avg Cost/Claim"
          value={formatCost(gs.avg_cost_per_claim ?? 0)}
          subtitle="Session average"
          icon="📈"
          color="purple"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Cost by Crew</h3>
          <CrewTable byCrew={byCrew} />
        </div>
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Cost by Claim Type</h3>
          <ClaimTypeTable byClaimType={byClaimType} />
        </div>
      </div>

      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Daily Spend (last 14 days)</h3>
        <DailyTable daily={daily} />
      </div>
    </div>
  );
}
