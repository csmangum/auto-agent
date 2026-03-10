interface TypeBadgeProps {
  type?: string;
}

const TYPE_STYLES: Record<string, string> = {
  new: 'bg-blue-500/15 text-blue-400 ring-blue-500/20',
  duplicate: 'bg-orange-500/15 text-orange-400 ring-orange-500/20',
  total_loss: 'bg-indigo-500/15 text-indigo-400 ring-indigo-500/20',
  fraud: 'bg-red-500/15 text-red-400 ring-red-500/20',
  partial_loss: 'bg-teal-500/15 text-teal-400 ring-teal-500/20',
};

const DEFAULT_STYLE = 'bg-gray-500/15 text-gray-400 ring-gray-500/20';

export default function TypeBadge({ type }: TypeBadgeProps) {
  const label = type ?? 'unclassified';
  const style = TYPE_STYLES[label] ?? DEFAULT_STYLE;

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ring-1 ring-inset ${style}`}>
      {label.replace(/_/g, ' ')}
    </span>
  );
}
