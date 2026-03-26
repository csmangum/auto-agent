import { useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';
import { useCostBreakdown } from '../api/queries';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { downloadCsv } from '../utils/csvDownload';

/** Crew colors for cost dashboard. New crews get default gray (#6B7280). */
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

const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: '#1f2937',
    border: '1px solid #374151',
    borderRadius: '0.5rem',
    color: '#e5e7eb',
    fontSize: '0.75rem',
  },
  itemStyle: { color: '#e5e7eb' },
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

function MonthlyTable({ monthly }: { monthly: Record<string, { total_cost_usd: number; total_tokens: number; claims: number }> }) {
  const entries = Object.entries(monthly ?? {}).sort((a, b) => b[0].localeCompare(a[0]));
  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500 py-4">No monthly data yet.</p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700/50 text-left text-xs uppercase tracking-wider text-gray-500">
            <th className="px-4 py-2 font-medium">Month</th>
            <th className="px-4 py-2 font-medium text-right">Cost</th>
            <th className="px-4 py-2 font-medium text-right">Tokens</th>
            <th className="px-4 py-2 font-medium text-right">Claims</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700/30">
          {entries.map(([month, data]) => (
            <tr key={month} className="hover:bg-gray-800/80 transition-colors">
              <td className="px-4 py-2.5 font-mono text-gray-400">{month}</td>
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

type DailyPreset = '30' | '60' | 'all';

function filterDailyEntries(
  daily: Record<string, { total_cost_usd: number; total_tokens: number; claims: number }>,
  preset: DailyPreset
): [string, { total_cost_usd: number; total_tokens: number; claims: number }][] {
  const entries = Object.entries(daily ?? {}).sort((a, b) => a[0].localeCompare(b[0]));
  if (preset === 'all') return entries;
  const days = preset === '30' ? 30 : 60;
  const cutoff = new Date();
  cutoff.setUTCHours(0, 0, 0, 0);
  cutoff.setUTCDate(cutoff.getUTCDate() - days);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return entries.filter(([d]) => d >= cutoffStr);
}

function DailyTable({
  entries,
}: {
  entries: [string, { total_cost_usd: number; total_tokens: number; claims: number }][];
}) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500 py-4">No daily data in this range.</p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700/50 text-left text-xs uppercase tracking-wider text-gray-500">
            <th className="px-4 py-2 font-medium">Date (UTC)</th>
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
  useDocumentTitle('LLM Cost');
  const [dailyPreset, setDailyPreset] = useState<DailyPreset>('30');
  const { data, isLoading, error } = useCostBreakdown();
  const tz = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'local', []);

  const dailyFiltered = useMemo(
    () => filterDailyEntries(data?.daily ?? {}, dailyPreset),
    [data?.daily, dailyPreset]
  );

  const dailyChartData = useMemo(
    () =>
      dailyFiltered.map(([date, d]) => ({
        date,
        cost: d.total_cost_usd,
        tokens: d.total_tokens,
        claims: d.claims,
      })),
    [dailyFiltered]
  );

  const monthlyChartData = useMemo(() => {
    const monthly = data?.monthly ?? {};
    return Object.entries(monthly)
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([month, d]) => ({
        month,
        cost: d.total_cost_usd,
        tokens: d.total_tokens,
        claims: d.claims,
      }));
  }, [data?.monthly]);

  const exportCrewCsv = () => {
    const byCrew = data?.by_crew ?? {};
    const rows: string[][] = [['crew', 'total_cost_usd', 'total_tokens', 'total_calls']];
    for (const [crew, d] of Object.entries(byCrew).sort(
      (a, b) => b[1].total_cost_usd - a[1].total_cost_usd
    )) {
      rows.push([crew, String(d.total_cost_usd), String(d.total_tokens), String(d.total_calls)]);
    }
    downloadCsv('llm-cost-by-crew.csv', rows);
  };

  const exportDailyCsv = () => {
    const rows: string[][] = [['date_utc', 'total_cost_usd', 'total_tokens', 'claims']];
    for (const [date, d] of dailyFiltered) {
      rows.push([date, String(d.total_cost_usd), String(d.total_tokens), String(d.claims)]);
    }
    downloadCsv('llm-cost-daily.csv', rows);
  };

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
        <div className="h-64 bg-gray-800/50 rounded-xl border border-gray-700/50 skeleton-shimmer" />
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

  const cost = data;
  const gs = cost?.global_stats;
  const byCrew = cost?.by_crew ?? {};
  const byClaimType = cost?.by_claim_type ?? {};
  const daily = cost?.daily ?? {};
  const monthly = cost?.monthly ?? {};

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="LLM Cost Dashboard"
        subtitle="Token and cost attribution by crew, claim type, and daily spend"
      />

      <p className="text-xs text-gray-500 -mt-2">
        Daily and monthly dates from the API are UTC calendar days. Your browser timezone:{' '}
        <span className="text-gray-400 font-mono">{tz}</span>.
      </p>

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
          value={gs?.total_claims ?? 0}
          subtitle="In current session"
          icon="📋"
          color="orange"
        />
        <StatCard
          title="Avg Cost/Claim"
          value={formatCost(gs?.avg_cost_per_claim ?? 0)}
          subtitle="Session average"
          icon="📈"
          color="purple"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5 min-h-[320px]">
          <h3 className="text-sm font-semibold text-gray-300 mb-1">Daily cost (USD)</h3>
          <p className="text-xs text-gray-500 mb-4">Time series for the selected range below.</p>
          {dailyChartData.length > 0 ? (
            <div className="w-full h-[260px] min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={dailyChartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3B82F6" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#3B82F6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 10 }} tickMargin={6} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} width={56} tickFormatter={(v) => `$${Number(v).toFixed(2)}`} />
                  <Tooltip
                    {...TOOLTIP_STYLE}
                    formatter={(value: number) => [formatCost(value), 'Cost']}
                    labelFormatter={(label) => `Date (UTC): ${label}`}
                  />
                  <Area type="monotone" dataKey="cost" stroke="#3B82F6" fill="url(#costFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-gray-500 py-12 text-center">No daily data in this range.</p>
          )}
        </div>

        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5 min-h-[320px]">
          <h3 className="text-sm font-semibold text-gray-300 mb-1">Monthly cost (USD)</h3>
          <p className="text-xs text-gray-500 mb-4">Aggregated by calendar month from the API.</p>
          {monthlyChartData.length > 0 ? (
            <div className="w-full h-[260px] min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={monthlyChartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="month" tick={{ fill: '#9ca3af', fontSize: 10 }} tickMargin={6} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} width={56} tickFormatter={(v) => `$${Number(v).toFixed(2)}`} />
                  <Tooltip {...TOOLTIP_STYLE} formatter={(value: number) => [formatCost(value), 'Cost']} />
                  <Bar dataKey="cost" fill="#8B5CF6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-gray-500 py-12 text-center">No monthly data yet.</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h3 className="text-sm font-semibold text-gray-300">Cost by Crew</h3>
            <button
              type="button"
              onClick={exportCrewCsv}
              className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-200 hover:bg-gray-600 transition-colors"
            >
              Download CSV
            </button>
          </div>
          <CrewTable byCrew={byCrew} />
        </div>
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Cost by Claim Type</h3>
          <ClaimTypeTable byClaimType={byClaimType} />
        </div>
      </div>

      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Monthly Spend</h3>
        <MonthlyTable monthly={monthly} />
      </div>

      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-300">Daily Spend</h3>
            <p className="text-xs text-gray-500 mt-1">
              Table and chart use the same UTC date range. Showing {dailyFiltered.length} of{' '}
              {Object.keys(daily).length} day bucket{Object.keys(daily).length === 1 ? '' : 's'} loaded.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="daily-range" className="text-xs text-gray-500 sr-only">
              Daily range
            </label>
            <select
              id="daily-range"
              value={dailyPreset}
              onChange={(e) => setDailyPreset(e.target.value as DailyPreset)}
              className="text-sm bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="30">Last 30 days (UTC)</option>
              <option value="60">Last 60 days (UTC)</option>
              <option value="all">All days</option>
            </select>
            <button
              type="button"
              onClick={exportDailyCsv}
              className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-200 hover:bg-gray-600 transition-colors"
            >
              Download daily CSV
            </button>
          </div>
        </div>
        <DailyTable entries={dailyFiltered} />
      </div>
    </div>
  );
}
