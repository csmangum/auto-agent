import StatusBadge from './StatusBadge';
import EmptyState from './EmptyState';
import StructuredOutputDisplay from './StructuredOutputDisplay';
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
  const dotColor = getDotColor(event.action);
  const hasStateDiff =
    event.before_state && event.after_state && event.action === 'status_change';
  const detailsRaw = event.details || event.after_state || '';
  const hasStatusChange = event.old_status && event.new_status;

  return (
    <div className="relative pl-10 animate-fade-in">
      <div className={`absolute left-2.5 top-2 w-3 h-3 rounded-full ${dotColor} ring-4 ring-gray-900`} />

      <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-gray-200 capitalize">
              {event.action?.replace(/_/g, ' ')}
            </span>
            {event.actor_id && (
              <span className="text-xs text-gray-500" title="Actor">
                by {event.actor_id}
              </span>
            )}
          </div>

          {hasStatusChange && (
            <div className="flex items-center gap-2 flex-wrap text-sm">
              <StatusBadge status={event.old_status} />
              <span className="text-gray-500 text-xs" aria-hidden>→</span>
              <StatusBadge status={event.new_status} />
            </div>
          )}

          {!hasStatusChange && event.new_status && (
            <StatusBadge status={event.new_status} />
          )}
        </div>

        {(detailsRaw || hasStateDiff) && (
          <div className="mt-3 pt-3 border-t border-gray-700/50 space-y-3 max-h-64 overflow-y-auto">
            {event.details && (
              <StructuredOutputDisplay
                value={event.details}
                compact
                variant="audit"
                maxLength={300}
              />
            )}
            {hasStateDiff && (
              <div className="space-y-3">
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500 mb-1">
                    Before
                  </p>
                  <StructuredOutputDisplay
                    value={event.before_state}
                    compact
                    variant="audit"
                    maxLength={300}
                  />
                </div>
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500 mb-1">
                    After
                  </p>
                  <StructuredOutputDisplay
                    value={event.after_state}
                    compact
                    variant="audit"
                    maxLength={300}
                  />
                </div>
              </div>
            )}
            {!event.details && !hasStateDiff && detailsRaw && (
              <StructuredOutputDisplay
                value={detailsRaw}
                compact
                variant="audit"
                maxLength={300}
              />
            )}
          </div>
        )}

        <p className="text-xs text-gray-600 mt-3">
          {formatDateTime(event.created_at) ?? '—'}
        </p>
      </div>
    </div>
  );
}
