import { Link } from 'react-router-dom';
import { useMemo } from 'react';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';
import { useReviewQueue, useOverdueTasks, useTaskStats } from '../api/queries';
import { formatDateTime } from '../utils/date';
import { CLAIM_PRIORITY_ORDER, CLAIM_PRIORITY_STYLES } from '../constants/priority';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { getErrorMessage } from '../utils/errorMessage';

const QUICK_ACTIONS = [
  { to: '/workbench/queue?assignee=me', label: 'My Assignments', icon: '👤', description: 'Claims assigned to you' },
  { to: '/workbench/queue', label: 'Assignment Queue', icon: '📥', description: 'Review and assign claims' },
  { to: '/workbench/diary', label: 'Diary / Calendar', icon: '📅', description: 'Tasks and deadlines' },
  { to: '/claims/new', label: 'New Claim', icon: '➕', description: 'Submit a new claim' },
];

export default function WorkbenchDashboard() {
  useDocumentTitle('Workbench');
  const {
    data: queueData,
    isLoading: queueLoading,
    isError: queueError,
    error: queueErr,
    refetch: refetchQueue,
    dataUpdatedAt: queueUpdatedAt,
  } = useReviewQueue({ limit: 200 }, { workbench: true });
  const {
    data: overdueData,
    isLoading: overdueLoading,
    isError: overdueError,
    error: overdueErr,
    refetch: refetchOverdue,
    dataUpdatedAt: overdueUpdatedAt,
  } = useOverdueTasks(5, { workbench: true });
  const {
    data: taskStats,
    isLoading: statsLoading,
    isError: statsError,
    error: statsErr,
    refetch: refetchStats,
    dataUpdatedAt: statsUpdatedAt,
  } = useTaskStats({ workbench: true });

  const anyError = queueError || overdueError || statsError;
  const lastUpdatedAt = Math.max(queueUpdatedAt, overdueUpdatedAt, statsUpdatedAt);

  const queueClaims = queueData?.claims ?? [];
  const queueTotal = queueData?.total ?? 0;
  const overdueTasks = overdueData?.tasks ?? [];
  const overdueTotal = overdueData?.total ?? 0;

  const priorityCounts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const c of queueClaims) {
    const p = c.priority ?? 'medium';
    priorityCounts[p] = (priorityCounts[p] ?? 0) + 1;
  }

  const activeTaskCount = (taskStats?.by_status?.['pending'] ?? 0)
    + (taskStats?.by_status?.['in_progress'] ?? 0)
    + (taskStats?.by_status?.['blocked'] ?? 0);

  const refetchAll = () => {
    void refetchQueue();
    void refetchOverdue();
    void refetchStats();
  };

  const queueErrMsg = useMemo(
    () => (queueError ? getErrorMessage(queueErr, 'Failed to load review queue') : ''),
    [queueError, queueErr]
  );
  const overdueErrMsg = useMemo(
    () => (overdueError ? getErrorMessage(overdueErr, 'Failed to load overdue tasks') : ''),
    [overdueError, overdueErr]
  );
  const statsErrMsg = useMemo(
    () => (statsError ? getErrorMessage(statsErr, 'Failed to load task stats') : ''),
    [statsError, statsErr]
  );

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="My Workbench"
        subtitle="Adjuster dashboard — your queue, tasks, and actions"
        actions={
          <div className="flex flex-col items-end gap-1">
            <button
              type="button"
              onClick={() => refetchAll()}
              className="text-xs px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-gray-200 hover:bg-gray-700 transition-colors"
            >
              Refresh
            </button>
            {lastUpdatedAt > 0 && (
              <span className="text-[10px] text-gray-500">
                Updated {new Date(lastUpdatedAt).toLocaleString()}
              </span>
            )}
          </div>
        }
      />

      {anyError && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-3">
          <p className="text-sm font-medium text-amber-200">Some workbench data could not be loaded</p>
          <ul className="text-xs text-amber-200/90 space-y-1 list-disc list-inside">
            {queueError && <li>Review queue: {queueErrMsg}</li>}
            {overdueError && <li>Overdue tasks: {overdueErrMsg}</li>}
            {statsError && <li>Task stats: {statsErrMsg}</li>}
          </ul>
          <button
            type="button"
            onClick={() => refetchAll()}
            className="text-xs px-3 py-1.5 rounded-lg bg-amber-600/80 text-white hover:bg-amber-500 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 stagger">
        <StatCard
          title="Review Queue"
          value={queueLoading ? '—' : queueError ? '—' : queueTotal}
          subtitle="Claims needing review"
          icon="📥"
          color="purple"
        />
        <StatCard
          title="Active Tasks"
          value={statsLoading ? '—' : statsError ? '—' : activeTaskCount}
          subtitle="Pending, in progress, blocked"
          icon="☑️"
          color="blue"
        />
        <StatCard
          title="Overdue"
          value={overdueLoading ? '—' : overdueError ? '—' : overdueTotal}
          subtitle="Past-due tasks"
          icon="⏰"
          color="red"
        />
        <StatCard
          title="Completed"
          value={statsLoading ? '—' : statsError ? '—' : (taskStats?.by_status?.['completed'] ?? 0)}
          subtitle="All-time completed tasks"
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
          {queueError ? (
            <div className="text-sm text-red-400 py-4">
              {queueErrMsg}
              <button
                type="button"
                onClick={() => void refetchQueue()}
                className="block mt-2 text-xs text-blue-400 hover:text-blue-300"
              >
                Retry
              </button>
            </div>
          ) : queueLoading ? (
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
              {CLAIM_PRIORITY_ORDER.map((p) => {
                const count = priorityCounts[p] ?? 0;
                const pct = queueTotal > 0 ? (count / queueTotal) * 100 : 0;
                const colors = CLAIM_PRIORITY_STYLES[p];
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
          {overdueError ? (
            <div className="text-sm text-red-400 py-4">
              {overdueErrMsg}
              <button
                type="button"
                onClick={() => void refetchOverdue()}
                className="block mt-2 text-xs text-blue-400 hover:text-blue-300"
              >
                Retry
              </button>
            </div>
          ) : overdueLoading ? (
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
          <span className="text-xs text-gray-500">{queueError ? '—' : `${queueTotal} total`}</span>
        </div>
        {queueError ? (
          <div className="text-sm text-red-400 py-4">
            {queueErrMsg}
            <button
              type="button"
              onClick={() => void refetchQueue()}
              className="block mt-2 text-xs text-blue-400 hover:text-blue-300"
            >
              Retry
            </button>
          </div>
        ) : queueLoading ? (
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
                  const colors = CLAIM_PRIORITY_STYLES[p] ?? CLAIM_PRIORITY_STYLES.medium;
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
