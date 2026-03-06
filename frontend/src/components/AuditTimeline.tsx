import { useState } from 'react';
import StatusBadge from './StatusBadge';
import { formatDateTime } from '../utils/date';
import type { AuditEvent } from '../api/types';

interface AuditTimelineProps {
  events: AuditEvent[];
}

function StateDiff({ label, jsonStr }: { label: string; jsonStr?: string }) {
  if (!jsonStr) return null;
  try {
    const obj = JSON.parse(jsonStr) as Record<string, unknown>;
    const hasNonNull = Object.values(obj).some((v) => v != null);
    if (!hasNonNull) return null;
    return (
      <div className="mt-2 text-xs">
        <span className="font-medium text-gray-500">{label}:</span>
        <pre className="mt-0.5 rounded bg-gray-50 p-2 font-mono text-gray-600 overflow-x-auto">
          {JSON.stringify(obj, null, 2)}
        </pre>
      </div>
    );
  } catch {
    return null;
  }
}

export default function AuditTimeline({ events }: AuditTimelineProps) {
  if (!events || events.length === 0) {
    return <p className="text-gray-500 text-sm py-4">No audit events.</p>;
  }

  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-200" />
      <div className="space-y-6">
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

  return (
    <div className="relative pl-10">
      <div className="absolute left-2.5 top-1.5 w-3 h-3 rounded-full bg-blue-500 border-2 border-white shadow" />

      <div className="bg-white border border-gray-100 rounded-lg p-4 shadow-sm">
        <div className="flex items-center gap-3 mb-2 flex-wrap">
          <span className="text-sm font-semibold text-gray-800 capitalize">
            {event.action?.replace(/_/g, ' ')}
          </span>
          {event.actor_id && (
            <span className="text-xs text-gray-500" title="Actor">
              by {event.actor_id}
            </span>
          )}
          {event.new_status && <StatusBadge status={event.new_status} />}
          {event.old_status && event.new_status && (
            <span className="text-xs text-gray-400">
              from <StatusBadge status={event.old_status} />
            </span>
          )}
        </div>

        {event.details && (
          <p className="text-sm text-gray-600 mt-1 break-words">
            {event.details.length > 300
              ? event.details.slice(0, 300) + '...'
              : event.details}
          </p>
        )}

        {hasStateDiff && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium"
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

        <p className="text-xs text-gray-400 mt-2">
          {formatDateTime(event.created_at) ?? '—'}
        </p>
      </div>
    </div>
  );
}
