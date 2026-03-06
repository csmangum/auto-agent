import StatusBadge from './StatusBadge';

export default function AuditTimeline({ events }) {
  if (!events || events.length === 0) {
    return <p className="text-gray-500 text-sm py-4">No audit events.</p>;
  }

  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-200" />
      <div className="space-y-6">
        {events.map((event, i) => (
          <div key={event.id || i} className="relative pl-10">
            {/* Dot */}
            <div className="absolute left-2.5 top-1.5 w-3 h-3 rounded-full bg-blue-500 border-2 border-white shadow" />

            <div className="bg-white border border-gray-100 rounded-lg p-4 shadow-sm">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-sm font-semibold text-gray-800 capitalize">
                  {event.action?.replace(/_/g, ' ')}
                </span>
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

              <p className="text-xs text-gray-400 mt-2">
                {event.created_at
                  ? new Date(event.created_at + 'Z').toLocaleString()
                  : '—'}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
