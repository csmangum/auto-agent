import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createClaimTask, updateTask } from '../api/client';
import type { CreateTaskPayload, UpdateTaskPayload } from '../api/client';
import type { ClaimTask, TaskStatus, TaskPriority, TaskType } from '../api/types';
import { queryKeys } from '../api/queries';
import { formatDateTime } from '../utils/date';
import EmptyState from './EmptyState';
import { getErrorMessage } from '../utils/errorMessage';

/** Backend validation on title; show inline only and avoid duplicate error toasts. */
function isTaskCreateTitleValidationError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : '';
  if (!msg.trim()) return false;
  const m = msg.toLowerCase();
  return m.includes('title') || m.includes('empty');
}

const TASK_TYPE_LABELS: Record<TaskType, string> = {
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

const STATUS_STYLES: Record<TaskStatus, { bg: string; text: string }> = {
  pending: { bg: 'bg-yellow-500/20', text: 'text-yellow-400' },
  in_progress: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  completed: { bg: 'bg-emerald-500/20', text: 'text-emerald-400' },
  cancelled: { bg: 'bg-gray-500/20', text: 'text-gray-400' },
  blocked: { bg: 'bg-red-500/20', text: 'text-red-400' },
};

const PRIORITY_STYLES: Record<TaskPriority, { bg: string; text: string; icon: string }> = {
  urgent: { bg: 'bg-red-500/20', text: 'text-red-400', icon: '🔴' },
  high: { bg: 'bg-orange-500/20', text: 'text-orange-400', icon: '🟠' },
  medium: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: '🟡' },
  low: { bg: 'bg-gray-500/20', text: 'text-gray-400', icon: '⚪' },
};

const TYPE_ICONS: Record<string, string> = {
  gather_information: '🔍',
  contact_witness: '👤',
  request_documents: '📄',
  schedule_inspection: '🔧',
  follow_up_claimant: '📞',
  review_documents: '📋',
  obtain_police_report: '🚔',
  medical_records_review: '🏥',
  appraisal: '💰',
  subrogation_follow_up: '⚖️',
  siu_referral: '🔎',
  contact_repair_shop: '🛠️',
  verify_coverage: '🛡️',
  other: '📌',
};

interface TaskPanelProps {
  claimId: string;
  tasks: ClaimTask[];
}

function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${s.bg} ${s.text}`}>
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function TaskPriorityBadge({ priority }: { priority: TaskPriority }) {
  const p = PRIORITY_STYLES[priority] ?? PRIORITY_STYLES.medium;
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${p.bg} ${p.text}`}>
      {p.icon} {priority}
    </span>
  );
}

function CreateTaskForm({ claimId, onDone }: { claimId: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [taskType, setTaskType] = useState<TaskType>('gather_information');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<TaskPriority>('medium');
  const [assignedTo, setAssignedTo] = useState('');
  const [dueDate, setDueDate] = useState('');

  const mutation = useMutation({
    mutationFn: (payload: CreateTaskPayload) => createClaimTask(claimId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.claimTasks(claimId) });
      setTitle('');
      setTaskType('gather_information');
      setDescription('');
      setPriority('medium');
      setAssignedTo('');
      setDueDate('');
      onDone();
      toast.success('Task created');
    },
    onError: (err) => {
      if (!isTaskCreateTitleValidationError(err)) {
        toast.error(getErrorMessage(err, 'Failed to create task'));
      }
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate({
      title,
      task_type: taskType,
      description: description || undefined,
      priority,
      assigned_to: assignedTo || undefined,
      due_date: dueDate || undefined,
    });
  };

  const errorMsg = mutation.error instanceof Error ? mutation.error.message : '';
  const isTitleError = mutation.isError && isTaskCreateTitleValidationError(mutation.error);

  return (
    <form onSubmit={handleSubmit} className="space-y-4 bg-gray-900/50 rounded-lg p-4 ring-1 ring-gray-700/50" aria-label="Create new task">
      <div>
        <label htmlFor="task-create-title" className="block text-xs text-gray-500 mb-1">Title *</label>
        <input
          id="task-create-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={500}
          aria-describedby={isTitleError ? 'task-create-title-error' : undefined}
          aria-invalid={isTitleError}
          className={`w-full bg-gray-800 border rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500 ${isTitleError ? 'border-red-500' : 'border-gray-700'}`}
          placeholder="e.g., Request police report from local PD"
        />
        {isTitleError && (
          <p id="task-create-title-error" className="mt-1 text-xs text-red-400">
            {errorMsg}
          </p>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="task-create-type" className="block text-xs text-gray-500 mb-1">Type *</label>
          <select
            id="task-create-type"
            value={taskType}
            onChange={(e) => setTaskType(e.target.value as TaskType)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {Object.entries(TASK_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="task-create-priority" className="block text-xs text-gray-500 mb-1">Priority</label>
          <select
            id="task-create-priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as TaskPriority)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
        </div>
      </div>
      <div>
        <label htmlFor="task-create-description" className="block text-xs text-gray-500 mb-1">Description</label>
        <textarea
          id="task-create-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          maxLength={5000}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
          placeholder="Detailed description of what needs to be done..."
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="task-create-assigned" className="block text-xs text-gray-500 mb-1">Assigned To</label>
          <input
            id="task-create-assigned"
            type="text"
            value={assignedTo}
            onChange={(e) => setAssignedTo(e.target.value)}
            maxLength={200}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="e.g., adjuster-jane"
          />
        </div>
        <div>
          <label htmlFor="task-create-due" className="block text-xs text-gray-500 mb-1">Due Date</label>
          <input
            id="task-create-due"
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onDone}
          className="px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200 transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={!title.trim() || mutation.isPending}
          className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {mutation.isPending ? 'Creating...' : 'Create Task'}
        </button>
      </div>
    </form>
  );
}

function TaskCard({ task, claimId }: { task: ClaimTask; claimId: string }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [notes, setNotes] = useState('');

  const statusMutation = useMutation({
    mutationFn: (payload: UpdateTaskPayload) => updateTask(task.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.claimTasks(claimId) });
      toast.success('Task updated');
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, 'Failed to update task'));
    },
  });

  const handleStatusChange = (newStatus: TaskStatus) => {
    const payload: UpdateTaskPayload = { status: newStatus };
    if (newStatus === 'completed' && notes.trim()) {
      payload.resolution_notes = notes;
    }
    statusMutation.mutate(payload);
  };

  const todayStr = new Date().toISOString().slice(0, 10);
  const isOverdue = task.due_date && task.status !== 'completed' && task.status !== 'cancelled'
    && task.due_date < todayStr;

  return (
    <div className={`rounded-lg bg-gray-900/50 ring-1 ${isOverdue ? 'ring-red-500/50' : 'ring-gray-700/50'} transition-all`}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={expanded ? `Collapse ${task.title}` : `Expand ${task.title}`}
        className="p-3 cursor-pointer hover:bg-gray-800/30 transition-colors rounded-lg"
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded((prev) => !prev);
          }
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-start gap-2 min-w-0">
            <span className="text-base shrink-0 mt-0.5">{TYPE_ICONS[task.task_type] ?? '📌'}</span>
            <div className="min-w-0">
              <p className={`text-sm font-medium ${task.status === 'completed' || task.status === 'cancelled' ? 'text-gray-500 line-through' : 'text-gray-200'}`}>
                {task.title}
              </p>
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                <TaskStatusBadge status={task.status as TaskStatus} />
                <TaskPriorityBadge priority={task.priority as TaskPriority} />
                <span className="text-xs text-gray-500">
                  {TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type}
                </span>
              </div>
            </div>
          </div>
          <span className="text-xs text-gray-600 shrink-0 mt-1">
            {expanded ? '▲' : '▼'}
          </span>
        </div>
        {isOverdue && (
          <p className="text-xs text-red-400 mt-1 ml-7">⚠ Overdue (due {task.due_date})</p>
        )}
      </div>

      {expanded && (
        <div className="px-3 pb-3 pt-0 border-t border-gray-700/50 space-y-3">
          {task.description && (
            <p className="text-sm text-gray-400 mt-3 whitespace-pre-wrap">{task.description}</p>
          )}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {task.assigned_to && (
              <div>
                <span className="text-gray-500">Assigned to: </span>
                <span className="text-gray-300">{task.assigned_to}</span>
              </div>
            )}
            {task.created_by && (
              <div>
                <span className="text-gray-500">Created by: </span>
                <span className="text-blue-400">{task.created_by}</span>
              </div>
            )}
            {task.due_date && (
              <div>
                <span className="text-gray-500">Due: </span>
                <span className={isOverdue ? 'text-red-400' : 'text-gray-300'}>{task.due_date}</span>
              </div>
            )}
            {task.created_at && (
              <div>
                <span className="text-gray-500">Created: </span>
                <span className="text-gray-300">{formatDateTime(task.created_at)}</span>
              </div>
            )}
          </div>
          {task.resolution_notes && (
            <div className="bg-gray-800/50 rounded p-2">
              <p className="text-xs text-gray-500 mb-1">Resolution Notes</p>
              <p className="text-sm text-gray-300 whitespace-pre-wrap">{task.resolution_notes}</p>
            </div>
          )}

          {task.status !== 'completed' && task.status !== 'cancelled' && (
            <div className="space-y-2">
              <label htmlFor={`task-resolution-notes-${task.id}`} className="sr-only">
                Resolution notes (optional)
              </label>
              <textarea
                id={`task-resolution-notes-${task.id}`}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
                placeholder="Resolution notes (optional)..."
              />
              <div className="flex gap-2 flex-wrap">
                {task.status === 'pending' && (
                  <button
                    onClick={() => handleStatusChange('in_progress')}
                    disabled={statusMutation.isPending}
                    className="px-2.5 py-1 text-xs bg-blue-600/80 text-white rounded hover:bg-blue-500 disabled:opacity-50 transition-colors"
                  >
                    Start
                  </button>
                )}
                {(task.status === 'pending' || task.status === 'in_progress' || task.status === 'blocked') && (
                  <button
                    onClick={() => handleStatusChange('completed')}
                    disabled={statusMutation.isPending}
                    className="px-2.5 py-1 text-xs bg-emerald-600/80 text-white rounded hover:bg-emerald-500 disabled:opacity-50 transition-colors"
                  >
                    Complete
                  </button>
                )}
                {task.status !== 'blocked' && (
                  <button
                    onClick={() => handleStatusChange('blocked')}
                    disabled={statusMutation.isPending}
                    className="px-2.5 py-1 text-xs bg-red-600/80 text-white rounded hover:bg-red-500 disabled:opacity-50 transition-colors"
                  >
                    Block
                  </button>
                )}
                <button
                  onClick={() => handleStatusChange('cancelled')}
                  disabled={statusMutation.isPending}
                  className="px-2.5 py-1 text-xs bg-gray-600/80 text-white rounded hover:bg-gray-500 disabled:opacity-50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function TaskPanel({ claimId, tasks }: TaskPanelProps) {
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<'all' | 'active' | 'completed'>('all');
  const safeTasks = Array.isArray(tasks) ? tasks : [];

  const filteredTasks = safeTasks.filter((t) => {
    if (filter === 'active') return t.status !== 'completed' && t.status !== 'cancelled';
    if (filter === 'completed') return t.status === 'completed' || t.status === 'cancelled';
    return true;
  });

  const activeCount = safeTasks.filter(t => t.status !== 'completed' && t.status !== 'cancelled').length;
  const completedCount = safeTasks.filter(t => t.status === 'completed' || t.status === 'cancelled').length;

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-gray-300">Tasks</h3>
          {safeTasks.length > 0 && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-yellow-400">{activeCount} active</span>
              <span className="text-gray-600">·</span>
              <span className="text-emerald-400">{completedCount} done</span>
            </div>
          )}
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-3 py-1 text-xs bg-blue-600/80 text-white rounded hover:bg-blue-500 transition-colors"
        >
          {showForm ? 'Cancel' : '+ New Task'}
        </button>
      </div>

      {showForm && (
        <div className="mb-4">
          <CreateTaskForm claimId={claimId} onDone={() => setShowForm(false)} />
        </div>
      )}

      {safeTasks.length > 0 && (
        <div className="flex gap-1 mb-3" role="group" aria-label="Task filter">
          {(['all', 'active', 'completed'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              aria-label={
                f === 'all'
                  ? `Show all tasks (${safeTasks.length})`
                  : f === 'active'
                    ? `Show active tasks (${activeCount})`
                    : `Show completed tasks (${completedCount})`
              }
              className={`px-2.5 py-1 text-xs rounded transition-colors ${
                filter === f
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'text-gray-500 hover:text-gray-300 hover:bg-gray-700/30'
              }`}
            >
              {f === 'all' ? `All (${safeTasks.length})` : f === 'active' ? `Active (${activeCount})` : `Done (${completedCount})`}
            </button>
          ))}
        </div>
      )}

      {filteredTasks.length === 0 ? (
        <EmptyState
          icon="✅"
          title={filter === 'all' ? 'No tasks' : filter === 'active' ? 'No active tasks' : 'No completed tasks'}
          description={filter === 'all' ? 'Create a task to track follow-up work for this claim.' : undefined}
        />
      ) : (
        <div className="space-y-2">
          {filteredTasks.map((task) => (
            <TaskCard key={task.id} task={task} claimId={claimId} />
          ))}
        </div>
      )}
    </div>
  );
}
