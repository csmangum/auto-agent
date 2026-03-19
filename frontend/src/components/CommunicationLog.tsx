import { useState, useMemo } from 'react';
import { formatDateTime } from '../utils/date';
import EmptyState from './EmptyState';
import type { AuditEvent, FollowUpMessage } from '../api/types';

interface NoteEntry {
  id?: number;
  note: string;
  actor_id: string;
  created_at?: string;
}

interface CommunicationLogProps {
  notes: NoteEntry[];
  followUps: FollowUpMessage[];
  auditEvents: AuditEvent[];
}

type EntryType = 'note' | 'follow_up' | 'audit';
type FilterType = 'all' | EntryType;

interface UnifiedEntry {
  type: EntryType;
  timestamp: string;
  actor: string;
  content: string;
  meta?: string;
  icon: string;
  color: string;
}

function mergeEntries(
  notes: NoteEntry[],
  followUps: FollowUpMessage[],
  auditEvents: AuditEvent[]
): UnifiedEntry[] {
  const entries: UnifiedEntry[] = [];

  for (const note of notes) {
    entries.push({
      type: 'note',
      timestamp: note.created_at ?? '',
      actor: note.actor_id,
      content: note.note,
      icon: '📝',
      color: 'blue',
    });
  }

  for (const msg of followUps) {
    entries.push({
      type: 'follow_up',
      timestamp: msg.created_at ?? '',
      actor: msg.user_type.replace(/_/g, ' '),
      content: msg.message_content,
      meta: msg.response_content
        ? `Response: ${msg.response_content}`
        : msg.status === 'sent'
          ? 'Awaiting response'
          : undefined,
      icon: '✉️',
      color: 'amber',
    });
  }

  // Only include meaningful audit events (status changes, assignments, escalations)
  const meaningfulActions = new Set([
    'status_change',
    'claim_assigned',
    'claim_approved',
    'claim_rejected',
    'claim_escalated',
    'claim_escalated_siu',
    'reserve_adjusted',
    'reserve_set',
    'payment_authorized',
    'payment_issued',
    'payment_cleared',
    'payment_voided',
    'claim_acknowledged',
    'review_completed',
    'info_requested',
    'claim_created',
    'workflow_started',
    'workflow_completed',
  ]);

  for (const event of auditEvents) {
    if (!meaningfulActions.has(event.action)) continue;
    let content = event.action.replace(/_/g, ' ');
    if (event.old_status && event.new_status) {
      content = `Status: ${event.old_status.replace(/_/g, ' ')} → ${event.new_status.replace(/_/g, ' ')}`;
    }
    if (event.details) {
      content += ` — ${event.details}`;
    }
    entries.push({
      type: 'audit',
      timestamp: event.created_at ?? '',
      actor: event.actor_id ?? 'system',
      content,
      icon: '📋',
      color: 'gray',
    });
  }

  // Sort chronologically, most recent first
  entries.sort((a, b) => {
    if (!a.timestamp && !b.timestamp) return 0;
    if (!a.timestamp) return 1;
    if (!b.timestamp) return -1;
    return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
  });

  return entries;
}

const COLOR_MAP: Record<string, { dot: string; bg: string; text: string; border: string }> = {
  blue: {
    dot: 'bg-blue-400',
    bg: 'bg-blue-500/5',
    text: 'text-blue-400',
    border: 'border-l-blue-500/50',
  },
  amber: {
    dot: 'bg-amber-400',
    bg: 'bg-amber-500/5',
    text: 'text-amber-400',
    border: 'border-l-amber-500/50',
  },
  gray: {
    dot: 'bg-gray-500',
    bg: 'bg-gray-800/30',
    text: 'text-gray-500',
    border: 'border-l-gray-600/50',
  },
};

export default function CommunicationLog({ notes, followUps, auditEvents }: CommunicationLogProps) {
  const [filter, setFilter] = useState<FilterType>('all');

  const allEntries = useMemo(
    () => mergeEntries(notes, followUps, auditEvents),
    [notes, followUps, auditEvents]
  );

  const filteredEntries = useMemo(
    () => (filter === 'all' ? allEntries : allEntries.filter((e) => e.type === filter)),
    [allEntries, filter]
  );

  const counts = useMemo(() => {
    const c = { note: 0, follow_up: 0, audit: 0 };
    for (const e of allEntries) c[e.type]++;
    return c;
  }, [allEntries]);

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-300">Communication Log</h3>
        <span className="text-xs text-gray-500">{allEntries.length} entries</span>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-4" role="group" aria-label="Communication filter">
        {([
          { key: 'all' as FilterType, label: `All (${allEntries.length})` },
          { key: 'note' as FilterType, label: `Notes (${counts.note})` },
          { key: 'follow_up' as FilterType, label: `Follow-ups (${counts.follow_up})` },
          { key: 'audit' as FilterType, label: `System (${counts.audit})` },
        ]).map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setFilter(tab.key)}
            aria-pressed={filter === tab.key}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              filter === tab.key
                ? 'bg-blue-500/20 text-blue-400'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-700/30'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Entries */}
      {filteredEntries.length === 0 ? (
        <EmptyState
          icon="💬"
          title="No communication"
          description="No communication entries match the current filter."
        />
      ) : (
        <div className="space-y-2">
          {filteredEntries.map((entry, i) => {
            const colors = COLOR_MAP[entry.color] ?? COLOR_MAP.gray;
            return (
              <div
                key={`${entry.type}-${entry.timestamp}-${i}`}
                className={`rounded-lg p-3 border-l-[3px] ${colors.border} ${colors.bg}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm">{entry.icon}</span>
                  <span className={`text-xs font-medium ${colors.text}`}>
                    {entry.actor}
                  </span>
                  <span className="text-xs text-gray-600">
                    {entry.type === 'note' ? 'Note' : entry.type === 'follow_up' ? 'Follow-up' : 'System'}
                  </span>
                  <span className="text-xs text-gray-600 ml-auto">
                    {formatDateTime(entry.timestamp)}
                  </span>
                </div>
                <p className="text-sm text-gray-300 whitespace-pre-wrap">{entry.content}</p>
                {entry.meta && (
                  <p className="text-xs text-gray-500 mt-1 italic">{entry.meta}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
