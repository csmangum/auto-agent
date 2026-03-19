import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';
import EmptyState from '../components/EmptyState';
import { useAllTasks, useTaskStats, useComplianceTemplates } from '../api/queries';
import { formatDateTime } from '../utils/date';
import type { ClaimTask, TaskStatus, TaskPriority, TaskType } from '../api/types';

const TASK_TYPE_LABELS: Record<string, string> = {
  gather_information: 'Gather Information',
  contact_witness: 'Contact Witness',
  request_documents: 'Request Documents',
  schedule_inspection: 'Schedule Inspection',
  follow_up_claimant: 'Follow Up Claimant',
  review_documents: 'Review Documents',
  obtain_police_report: 'Obtain Police Report',
  medical_records_review: 'Medical Records Review',
  appraisal: 'Appraisal',
  subrogation_follow_up: 'Subrogation Follow-up',
  siu_referral: 'SIU Referral',
  contact_repair_shop: 'Contact Repair Shop',
  verify_coverage: 'Verify Coverage',
  other: 'Other',
};

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  pending: { bg: 'bg-yellow-500/20', text: 'text-yellow-400' },
  in_progress: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  completed: { bg: 'bg-emerald-500/20', text: 'text-emerald-400' },
  cancelled: { bg: 'bg-gray-500/20', text: 'text-gray-400' },
  blocked: { bg: 'bg-red-500/20', text: 'text-red-400' },
};

const PRIORITY_DOT: Record<string, string> = {
  urgent: 'bg-red-400',
  high: 'bg-orange-400',
  medium: 'bg-yellow-400',
  low: 'bg-gray-400',
};

const selectClasses =
  'border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-800 text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors';

type ViewMode = 'list' | 'calendar';

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number): number {
  return new Date(year, month, 1).getDay();
}

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

interface CalendarViewProps {
  tasks: ClaimTask[];
  year: number;
  month: number;
  onPrevMonth: () => void;
  onNextMonth: () => void;
}

function CalendarView({ tasks, year, month, onPrevMonth, onNextMonth }: CalendarViewProps) {
  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfWeek(year, month);
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  // Group tasks by due_date
  const tasksByDate = useMemo(() => {
    const map: Record<string, ClaimTask[]> = {};
    for (const t of tasks) {
      if (!t.due_date) continue;
      const d = t.due_date.slice(0, 10);
      if (!map[d]) map[d] = [];
      map[d].push(t);
    }
    return map;
  }, [tasks]);

  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
      <div className="flex items-center justify-between mb-4">
        <button onClick={onPrevMonth} className="px-2 py-1 text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded transition-colors">←</button>
        <h3 className="text-sm font-semibold text-gray-200">{MONTH_NAMES[month]} {year}</h3>
        <button onClick={onNextMonth} className="px-2 py-1 text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded transition-colors">→</button>
      </div>
      <div className="grid grid-cols-7 gap-px">
        {DAY_NAMES.map((d) => (
          <div key={d} className="text-center text-xs font-medium text-gray-500 pb-2">{d}</div>
        ))}
        {cells.map((day, i) => {
          if (day === null) {
            return <div key={`empty-${i}`} className="min-h-[80px] bg-gray-900/30 rounded" />;
          }
          const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          const dayTasks = tasksByDate[dateStr] ?? [];
          const isToday = dateStr === todayStr;

          return (
            <div
              key={dateStr}
              className={`min-h-[80px] p-1 rounded border transition-colors ${
                isToday
                  ? 'border-blue-500/50 bg-blue-500/5'
                  : 'border-gray-800 bg-gray-900/30 hover:bg-gray-900/50'
              }`}
            >
              <div className={`text-xs font-medium mb-1 ${isToday ? 'text-blue-400' : 'text-gray-500'}`}>
                {day}
              </div>
              <div className="space-y-0.5">
                {dayTasks.slice(0, 3).map((t) => {
                  const dotColor = PRIORITY_DOT[t.priority] ?? PRIORITY_DOT.medium;
                  return (
                    <Link
                      key={t.id}
                      to={`/claims/${t.claim_id}`}
                      className="flex items-center gap-1 group"
                      title={`${t.title} (${t.claim_id})`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
                      <span className="text-[10px] text-gray-400 truncate group-hover:text-gray-200 transition-colors">
                        {t.title}
                      </span>
                    </Link>
                  );
                })}
                {dayTasks.length > 3 && (
                  <span className="text-[10px] text-gray-600">+{dayTasks.length - 3} more</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function DiaryCalendar() {
  const [view, setView] = useState<ViewMode>('list');
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [assignedFilter, setAssignedFilter] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const offset = (page - 1) * pageSize;

  const now = new Date();
  const [calYear, setCalYear] = useState(now.getFullYear());
  const [calMonth, setCalMonth] = useState(now.getMonth());

  // Calendar view: fetch tasks for displayed month only (date range limits result set)
  const calFirstDay = `${calYear}-${String(calMonth + 1).padStart(2, '0')}-01`;
  const calLastDay = `${calYear}-${String(calMonth + 1).padStart(2, '0')}-${String(
    new Date(calYear, calMonth + 1, 0).getDate()
  ).padStart(2, '0')}`;

  const params = view === 'calendar'
    ? {
        limit: 500,
        offset: 0,
        due_date_from: calFirstDay,
        due_date_to: calLastDay,
        ...(statusFilter && { status: statusFilter }),
        ...(typeFilter && { task_type: typeFilter }),
        ...(assignedFilter && { assigned_to: assignedFilter }),
      }
    : {
        limit: pageSize,
        offset,
        ...(statusFilter && { status: statusFilter }),
        ...(typeFilter && { task_type: typeFilter }),
        ...(assignedFilter && { assigned_to: assignedFilter }),
      };

  const { data: tasksData, isLoading: tasksLoading } = useAllTasks(params);
  const { data: taskStats, isLoading: statsLoading } = useTaskStats();
  const { data: templatesData } = useComplianceTemplates();

  const tasks = tasksData?.tasks ?? [];
  const total = tasksData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const templates = templatesData?.templates ?? [];

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  const handlePrevMonth = () => {
    if (calMonth === 0) {
      setCalMonth(11);
      setCalYear((y) => y - 1);
    } else {
      setCalMonth((m) => m - 1);
    }
  };

  const handleNextMonth = () => {
    if (calMonth === 11) {
      setCalMonth(0);
      setCalYear((y) => y + 1);
    } else {
      setCalMonth((m) => m + 1);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="Diary / Calendar"
        subtitle="Cross-claim task management and scheduling"
        backTo="/workbench"
        backLabel="Workbench"
        actions={
          <div className="flex items-center gap-2">
            <div className="flex items-center bg-gray-800 rounded-lg p-0.5 ring-1 ring-gray-700">
              <button
                onClick={() => setView('list')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  view === 'list' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                List
              </button>
              <button
                onClick={() => setView('calendar')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  view === 'calendar' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Calendar
              </button>
            </div>
          </div>
        }
      />

      {/* Task stats */}
      {!statsLoading && taskStats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard title="Total" value={taskStats.total} icon="📋" color="blue" />
          <StatCard title="Pending" value={taskStats.by_status?.['pending'] ?? 0} icon="⏳" color="orange" />
          <StatCard title="In Progress" value={taskStats.by_status?.['in_progress'] ?? 0} icon="🔄" color="blue" />
          <StatCard title="Overdue" value={taskStats.overdue} icon="⚠️" color="red" />
          <StatCard title="Completed" value={taskStats.by_status?.['completed'] ?? 0} icon="✅" color="green" />
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 p-4 bg-gray-800/30 rounded-xl border border-gray-700/30">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className={selectClasses}
        >
          <option value="">All Statuses</option>
          {(['pending', 'in_progress', 'completed', 'cancelled', 'blocked'] as TaskStatus[]).map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
          ))}
        </select>

        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
          className={selectClasses}
        >
          <option value="">All Types</option>
          {(Object.keys(TASK_TYPE_LABELS) as TaskType[]).map((t) => (
            <option key={t} value={t}>{TASK_TYPE_LABELS[t]}</option>
          ))}
        </select>

        <input
          type="text"
          value={assignedFilter}
          onChange={(e) => { setAssignedFilter(e.target.value); setPage(1); }}
          placeholder="Assigned to..."
          className={selectClasses + ' w-40'}
        />

        {(statusFilter || typeFilter || assignedFilter) && (
          <button
            type="button"
            onClick={() => { setStatusFilter(''); setTypeFilter(''); setAssignedFilter(''); setPage(1); }}
            className="text-xs text-gray-400 hover:text-gray-200 px-3 py-2 rounded-lg hover:bg-gray-700 transition-colors"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Compliance templates */}
      {templates.length > 0 && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Compliance Deadline Templates</h3>
          <div className="flex flex-wrap gap-2">
            {templates.map((t, i) => (
              <div
                key={i}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-900/50 ring-1 ring-gray-700/50 text-xs"
                title={t.description}
              >
                <span className="text-amber-400">📋</span>
                <span className="text-gray-300">{t.title}</span>
                <span className="text-gray-600">({t.days}d)</span>
                {t.state && <span className="text-gray-600">· {t.state}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Content */}
      {view === 'calendar' ? (
        <CalendarView
          tasks={tasks}
          year={calYear}
          month={calMonth}
          onPrevMonth={handlePrevMonth}
          onNextMonth={handleNextMonth}
        />
      ) : (
        <>
          {/* Task list */}
          <div className="bg-gray-800/50 rounded-xl border border-gray-700/50">
            {tasksLoading ? (
              <div className="p-8 space-y-3">
                {[...Array(8)].map((_, i) => (
                  <div key={i} className="h-12 bg-gray-700/30 rounded skeleton-shimmer" />
                ))}
              </div>
            ) : tasks.length === 0 ? (
              <EmptyState
                icon="📅"
                title="No tasks found"
                description="No tasks match your current filters."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700/50 text-left text-gray-500 text-xs uppercase tracking-wider">
                      <th className="px-4 py-3 font-medium">Task</th>
                      <th className="px-4 py-3 font-medium">Type</th>
                      <th className="px-4 py-3 font-medium">Claim</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Priority</th>
                      <th className="px-4 py-3 font-medium">Assigned</th>
                      <th className="px-4 py-3 font-medium">Due</th>
                      <th className="px-4 py-3 font-medium">Created</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800/50">
                    {tasks.map((task) => {
                      const ss = STATUS_STYLES[task.status] ?? STATUS_STYLES.pending;
                      const isOverdue = task.due_date && task.status !== 'completed' && task.status !== 'cancelled' && task.due_date < todayStr;
                      const dotColor = PRIORITY_DOT[task.priority as TaskPriority] ?? PRIORITY_DOT.medium;

                      return (
                        <tr key={task.id} className="hover:bg-gray-800/50 transition-colors">
                          <td className="px-4 py-3">
                            <p className={`text-sm font-medium ${task.status === 'completed' || task.status === 'cancelled' ? 'text-gray-500 line-through' : 'text-gray-200'}`}>
                              {task.title}
                            </p>
                            {isOverdue && <p className="text-xs text-red-400 mt-0.5">⚠ Overdue</p>}
                          </td>
                          <td className="px-4 py-3 text-gray-400 text-xs">
                            {TASK_TYPE_LABELS[task.task_type] ?? task.task_type}
                          </td>
                          <td className="px-4 py-3">
                            <Link to={`/claims/${task.claim_id}`} className="text-blue-400 hover:text-blue-300 font-mono text-xs">
                              {task.claim_id}
                            </Link>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`text-xs px-2 py-0.5 rounded ${ss.bg} ${ss.text}`}>
                              {task.status.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className="flex items-center gap-1.5">
                              <span className={`w-2 h-2 rounded-full ${dotColor}`} />
                              <span className="text-xs text-gray-400 capitalize">{task.priority}</span>
                            </span>
                          </td>
                          <td className="px-4 py-3 text-gray-400 text-xs">
                            {task.assigned_to || <span className="text-gray-600">—</span>}
                          </td>
                          <td className={`px-4 py-3 text-xs ${isOverdue ? 'text-red-400 font-medium' : 'text-gray-500'}`}>
                            {task.due_date ?? '—'}
                          </td>
                          <td className="px-4 py-3 text-gray-500 text-xs">
                            {formatDateTime(task.created_at)}
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
          {total > pageSize && (
            <div className="flex items-center justify-between gap-4">
              <p className="text-sm text-gray-500">
                Showing {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 text-sm border border-gray-700 rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  ←
                </button>
                <span className="px-3 py-1.5 text-sm text-gray-400">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 text-sm border border-gray-700 rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  →
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
