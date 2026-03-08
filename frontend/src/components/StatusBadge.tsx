interface StatusBadgeProps {
  status?: string;
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  processing: 'bg-blue-100 text-blue-800',
  open: 'bg-green-100 text-green-800',
  closed: 'bg-gray-100 text-gray-700',
  duplicate: 'bg-orange-100 text-orange-800',
  fraud_suspected: 'bg-red-100 text-red-800',
  fraud_confirmed: 'bg-red-200 text-red-900',
  needs_review: 'bg-purple-100 text-purple-800',
  pending_info: 'bg-yellow-200 text-yellow-900',
  partial_loss: 'bg-teal-100 text-teal-800',
  under_investigation: 'bg-amber-100 text-amber-800',
  denied: 'bg-red-100 text-red-700',
  settled: 'bg-emerald-100 text-emerald-800',
  disputed: 'bg-pink-100 text-pink-800',
  failed: 'bg-red-200 text-red-900',
  unknown: 'bg-gray-100 text-gray-600',
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const label = status ?? 'unknown';
  const colors = STATUS_COLORS[label] ?? STATUS_COLORS.unknown;

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors}`}>
      {label.replace(/_/g, ' ')}
    </span>
  );
}
