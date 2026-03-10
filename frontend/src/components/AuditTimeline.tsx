import { useState } from 'react';
import StatusBadge from './StatusBadge';
import EmptyState from './EmptyState';
import { formatDateTime } from '../utils/date';
import type { AuditEvent } from '../api/types';

interface AuditTimelineProps {
  events: AuditEvent[];
}

const ACTION_DOT_COLORS: Record<string, string> = {
  claim_created: 'bg-green-500',
  status_change: 'bg-blue-500',
  escalated_to_siu: 'bg-red-500',
  escalation_check: 'bg-purple-500',
  assigned: 'bg-amber-500',
  approved: 'bg-emerald-500',
  rejected: 'bg-red-500',
  reprocessed: 'bg-indigo-500',
};

function getDotColor(action: string): string {
  if (ACTION_DOT_COLORS[action]) return ACTION_DOT_COLORS[action];
  if (action.includes('fraud')) return 'bg-red-500';
  if (action.includes('escalat')) return 'bg-purple-500';
  return 'bg-blue-500';
}

function StateDiff({ label, jsonStr }: { label: string; jsonStr?: string }) {
  if (!jsonStr) return null;
  let displayStr: string | null = null;
  try {
    const obj = JSON.parse(jsonStr) as Record<string, unknown>;
    const hasNonNull = Object.values(obj).some((v) => v != null);
    if (hasNonNull) {
      displayStr = JSON.stringify(obj, null, 2);
    }
  } catch {
    return null;
  }
  if (!displayStr) return null;
  return (
    <div className="mt-2 text-xs">
      <span className="font-medium text-gray-500">{label}:</span>
      <pre className="mt-0.5 rounded-lg bg-gray-800 p-2 font-mono text-gray-400 overflow-x-auto ring-1 ring-gray-700/50">
        {displayStr}
      </pre>
    </div>
  );
}

export default function AuditTimeline({ events }: AuditTimelineProps) {
  if (!events || events.length === 0) {
    return (
      <EmptyState
        icon="📜"
        title="No audit events"
        description="No audit history has been recorded for this claim yet."
      />
    );
  }

  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-px bg-gray-700/50" />
      <div className="space-y-4">
        {events.map((event, i) => (
          <AuditEventCard key={event.id ?? i} event={event} />
        ))}
      </div>
    </div>
  );
}

function AuditEventCard({ event }: { event: AuditEvent }) {
  const [expanded, setExpanded] = useState(false);
  const hasStateDiff =
    (event.before_state || event.after_state) && event.action === 'status_change';
  const dotColor = getDotColor(event.action);

  return (
    <div className="relative pl-10 animate-fade-in">
      <div className={`absolute left-2.5 top-2 w-3 h-3 rounded-full ${dotColor} ring-4 ring-gray-900`} />

      <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-4">
        <div className="flex items-center gap-3 mb-1 flex-wrap">
          <span className="text-sm font-semibold text-gray-200 capitalize">
            {event.action?.replace(/_/g, ' ')}
          </span>
          {event.actor_id && (
            <span className="text-xs text-gray-500" title="Actor">
              by {event.actor_id}
            </span>
          )}
          {event.new_status && <StatusBadge status={event.new_status} />}
          {event.old_status && event.new_status && (
            <span className="text-xs text-gray-500">
              from <StatusBadge status={event.old_status} />
            </span>
          )}
        </div>

        {event.details && (
          <p className="text-sm text-gray-400 mt-1 break-words">
            {event.details.length > 300
              ? event.details.slice(0, 300) + '…'
              : event.details}
          </p>
        )}

        {hasStateDiff && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
            >
              {expanded ? 'Hide state diff' : 'Show state diff'}
            </button>
            {expanded && (
              <div className="mt-2 space-y-2">
                <StateDiff label="Before" jsonStr={event.before_state} />
                <StateDiff label="After" jsonStr={event.after_state} />
              </div>
            )}
          </div>
        )}

        <p className="text-xs text-gray-600 mt-2">
          {formatDateTime(event.created_at) ?? '—'}
        </p>
      </div>
    </div>
  );
}
