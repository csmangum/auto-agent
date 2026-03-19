import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';
import { useReviewQueue, useOverdueTasks, useTaskStats } from '../api/queries';
import { formatDateTime } from '../utils/date';

const PRIORITY_ORDER = ['critical', 'high', 'medium', 'low'] as const;

const PRIORITY_COLORS: Record<string, { bg: string; text: string; icon: string }> = {
  critical: { bg: 'bg-red-500/20', text: 'text-red-400', icon: '🔴' },
  high: { bg: 'bg-orange-500/20', text: 'text-orange-400', icon: '🟠' },
  medium: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: '🟡' },
  low: { bg: 'bg-gray-500/20', text: 'text-gray-400', icon: '⚪' },
};

const QUICK_ACTIONS = [
  { to: '/workbench/queue', label: 'Assignment Queue', icon: '📥', description: 'Review and assign claims' },
  { to: '/workbench/diary', label: 'Diary / Calendar', icon: '📅', description: 'Tasks and deadlines' },
  { to: '/claims/new', label: 'New Claim', icon: '➕', description: 'Submit a new claim' },
  { to: '/claims', label: 'All Claims', icon: '📋', description: 'Browse all claims' },
];

export default function WorkbenchDashboard() {
  const { data: queueData, isLoading: queueLoading } = useReviewQueue({ limit: 200 });
  const { data: overdueData, isLoading: overdueLoading } = useOverdueTasks(5);
  const { data: taskStats, isLoading: statsLoading } = useTaskStats();
  const loading = queueLoading || overdueLoading || statsLoading;

  const queueClaims = queueData?.claims ?? [];
  const queueTotal = queueData?.total ?? 0;
  const overdueTasks = overdueData?.tasks ?? [];
  const overdueTotal = overdueData?.total ?? 0;

  // Priority breakdown
  const priorityCounts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const c of queueClaims) {
    const p = c.priority ?? 'medium';
    priorityCounts[p] = (priorityCounts[p] ?? 0) + 1;
  }

  const activeTaskCount = (taskStats?.by_status?.['pending'] ?? 0)
    + (taskStats?.by_status?.['in_progress'] ?? 0)
    + (taskStats?.by_status?.['blocked'] ?? 0);

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="My Workbench"
        subtitle="Adjuster dashboard — your queue, tasks, and actions"
      />

      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 stagger">
        <StatCard
          title="Review Queue"
          value={loading ? '—' : queueTotal}
          subtitle="Claims needing review"
          icon="📥"
          color="purple"
        />
        <StatCard
          title="Active Tasks"
          value={loading ? '—' : activeTaskCount}
          subtitle="Pending, in progress, blocked"
          icon="☑️"
          color="blue"
        />
        <StatCard
          title="Overdue"
          value={loading ? '—' : overdueTotal}
          subtitle="Past-due tasks"
          icon="⏰"
          color="red"
        />
        <StatCard
          title="Completed Today"
          value={loading ? '—' : (taskStats?.by_status?.['completed'] ?? 0)}
          subtitle="Tasks completed"
          icon="✅"
          color="green"
        />
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {QUICK_ACTIONS.map((action) => (
          <Link
            key={action.to}
            to={action.to}
            className="flex flex-col gap-1.5 px-4 py-3 rounded-lg bg-gray-800/50 border border-gray-700/50 text-sm text-gray-300 hover:bg-gray-800 hover:text-gray-100 hover:border-gray-600 transition-all group"
          >
            <div className="flex items-center gap-2">
              <span className="text-base group-hover:scale-110 transition-transform">{action.icon}</span>
              <span className="font-medium">{action.label}</span>
            </div>
            <span className="text-xs text-gray-500">{action.description}</span>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Priority breakdown */}
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-gray-300">Queue by Priority</h3>
            <Link
              to="/workbench/queue"
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              View queue →
            </Link>
          </div>
          {loading ? (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-8 bg-gray-700/30 rounded skeleton-shimmer" />
              ))}
            </div>
          ) : queueTotal === 0 ? (
            <div className="text-center py-8">
              <span className="text-3xl opacity-30">✅</span>
              <p className="text-sm text-gray-500 mt-2">Queue is clear</p>
            </div>
          ) : (
            <div className="space-y-2">
              {PRIORITY_ORDER.map((p) => {
                const count = priorityCounts[p] ?? 0;
                const pct = queueTotal > 0 ? (count / queueTotal) * 100 : 0;
                const colors = PRIORITY_COLORS[p];
                return (
                  <div key={p} className="flex items-center gap-3">
                    <span className="text-sm w-5">{colors.icon}</span>
                    <span className={`text-xs font-medium capitalize w-16 ${colors.text}`}>{p}</span>
                    <div className="flex-1 h-6 bg-gray-900/50 rounded-lg overflow-hidden">
                      <div
                        className={`h-full ${colors.bg} rounded-lg transition-all duration-500`}
                        style={{ width: `${Math.max(pct, count > 0 ? 5 : 0)}%` }}
                      />
                    </div>
                    <span className="text-sm font-mono text-gray-400 w-8 text-right">{count}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Overdue tasks */}
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-gray-300">Overdue Tasks</h3>
            <Link
              to="/workbench/diary"
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              View all →
            </Link>
          </div>
          {loading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-12 bg-gray-700/30 rounded skeleton-shimmer" />
              ))}
            </div>
          ) : overdueTasks.length === 0 ? (
            <div className="text-center py-8">
              <span className="text-3xl opacity-30">🎉</span>
              <p className="text-sm text-gray-500 mt-2">No overdue tasks</p>
            </div>
          ) : (
            <div className="space-y-2">
              {overdueTasks.map((task) => (
                <Link
                  key={task.id}
                  to={`/claims/${task.claim_id}`}
                  className="block rounded-lg bg-gray-900/50 p-3 ring-1 ring-red-500/30 hover:ring-red-500/50 transition-all"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-200 truncate">{task.title}</p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {task.claim_id} · Due {task.due_date}
                      </p>
                    </div>
                    <span className="text-xs text-red-400 shrink-0">⚠ Overdue</span>
                  </div>
                </Link>
              ))}
              {overdueTotal > overdueTasks.length && (
                <p className="text-xs text-gray-500 text-center pt-1">
                  +{overdueTotal - overdueTasks.length} more overdue tasks
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Recent queue claims */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-300">Recent Queue Claims</h3>
          <span className="text-xs text-gray-500">{queueTotal} total</span>
        </div>
        {loading ? (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-10 bg-gray-700/30 rounded skeleton-shimmer" />
            ))}
          </div>
        ) : queueClaims.length === 0 ? (
          <div className="text-center py-8">
            <span className="text-3xl opacity-30">📋</span>
            <p className="text-sm text-gray-500 mt-2">No claims in the review queue</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50 text-left text-gray-500 text-xs uppercase tracking-wider">
                  <th className="px-3 py-2 font-medium">Priority</th>
                  <th className="px-3 py-2 font-medium">Claim ID</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Assignee</th>
                  <th className="px-3 py-2 font-medium">In Queue Since</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {queueClaims.slice(0, 10).map((claim) => {
                  const p = claim.priority ?? 'medium';
                  const colors = PRIORITY_COLORS[p] ?? PRIORITY_COLORS.medium;
                  return (
                    <tr key={claim.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="px-3 py-2">
                        <span className={`text-xs px-2 py-0.5 rounded ${colors.bg} ${colors.text} capitalize`}>
                          {colors.icon} {p}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <Link to={`/claims/${claim.id}`} className="text-blue-400 hover:text-blue-300 font-mono">
                          {claim.id}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-gray-400 capitalize">
                        {(claim.claim_type ?? '—').replace(/_/g, ' ')}
                      </td>
                      <td className="px-3 py-2 text-gray-400">
                        {claim.assignee || <span className="text-gray-600">Unassigned</span>}
                      </td>
                      <td className="px-3 py-2 text-gray-500 text-xs">
                        {formatDateTime(claim.review_started_at) ?? '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
