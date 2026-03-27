interface StatusBadgeProps {
  status?: string;
}

const STATUS_STYLES: Record<string, { dot: string; badge: string }> = {
  pending:              { dot: 'bg-yellow-400', badge: 'bg-yellow-500/15 text-yellow-400 ring-yellow-500/20' },
  processing:           { dot: 'bg-blue-400',   badge: 'bg-blue-500/15 text-blue-400 ring-blue-500/20' },
  open:                 { dot: 'bg-green-400',  badge: 'bg-green-500/15 text-green-400 ring-green-500/20' },
  closed:               { dot: 'bg-gray-400',   badge: 'bg-gray-500/15 text-gray-400 ring-gray-500/20' },
  duplicate:            { dot: 'bg-orange-400', badge: 'bg-orange-500/15 text-orange-400 ring-orange-500/20' },
  fraud_suspected:      { dot: 'bg-red-400',    badge: 'bg-red-500/15 text-red-400 ring-red-500/20' },
  fraud_confirmed:      { dot: 'bg-red-500',    badge: 'bg-red-500/20 text-red-300 ring-red-500/30' },
  needs_review:         { dot: 'bg-purple-400', badge: 'bg-purple-500/15 text-purple-400 ring-purple-500/20' },
  pending_info:         { dot: 'bg-yellow-500', badge: 'bg-yellow-500/20 text-yellow-300 ring-yellow-500/30' },
  partial_loss:         { dot: 'bg-teal-400',   badge: 'bg-teal-500/15 text-teal-400 ring-teal-500/20' },
  under_investigation:  { dot: 'bg-amber-400',  badge: 'bg-amber-500/15 text-amber-400 ring-amber-500/20' },
  denied:               { dot: 'bg-red-500',    badge: 'bg-red-500/15 text-red-400 ring-red-500/20' },
  settled:              { dot: 'bg-emerald-400', badge: 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/20' },
  disputed:             { dot: 'bg-pink-400',   badge: 'bg-pink-500/15 text-pink-400 ring-pink-500/20' },
  dispute_resolved:     { dot: 'bg-indigo-400', badge: 'bg-indigo-500/15 text-indigo-400 ring-indigo-500/20' },
  failed:               { dot: 'bg-red-500',    badge: 'bg-red-500/20 text-red-300 ring-red-500/30' },
  unknown:              { dot: 'bg-gray-500',   badge: 'bg-gray-500/15 text-gray-400 ring-gray-500/20' },
};

const DEFAULT = STATUS_STYLES.unknown;

export default function StatusBadge({ status }: StatusBadgeProps) {
  const label = status ?? 'unknown';
  const styles = STATUS_STYLES[label] ?? DEFAULT;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ring-1 ring-inset ${styles.badge}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`} aria-hidden="true" />
      {label.replace(/_/g, ' ')}
    </span>
  );
}
