interface StatCardProps {
  title: string;
  value: number | string;
  subtitle?: string;
  icon?: string;
  color?: 'blue' | 'green' | 'purple' | 'orange' | 'red' | 'teal' | 'gray';
}

const COLOR_MAP: Record<string, { card: string; icon: string }> = {
  blue:   { card: 'bg-blue-500/10 ring-blue-500/20 text-blue-400',     icon: 'text-blue-500/30' },
  green:  { card: 'bg-emerald-500/10 ring-emerald-500/20 text-emerald-400', icon: 'text-emerald-500/30' },
  purple: { card: 'bg-purple-500/10 ring-purple-500/20 text-purple-400',   icon: 'text-purple-500/30' },
  orange: { card: 'bg-orange-500/10 ring-orange-500/20 text-orange-400',   icon: 'text-orange-500/30' },
  red:    { card: 'bg-red-500/10 ring-red-500/20 text-red-400',       icon: 'text-red-500/30' },
  teal:   { card: 'bg-teal-500/10 ring-teal-500/20 text-teal-400',     icon: 'text-teal-500/30' },
  gray:   { card: 'bg-gray-500/10 ring-gray-500/20 text-gray-400',     icon: 'text-gray-500/30' },
};

export default function StatCard({ title, value, subtitle, icon, color = 'blue' }: StatCardProps) {
  const colors = COLOR_MAP[color] ?? COLOR_MAP.blue;

  return (
    <div className={`rounded-xl ring-1 p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/20 ${colors.card}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium opacity-75">{title}</p>
          <p className="text-3xl font-bold mt-1 text-gray-100">{value}</p>
          {subtitle && <p className="text-xs mt-1 opacity-60">{subtitle}</p>}
        </div>
        {icon && <span className={`text-4xl ${colors.icon}`}>{icon}</span>}
      </div>
    </div>
  );
}
