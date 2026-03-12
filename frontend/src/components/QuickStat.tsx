interface QuickStatProps {
  label: string;
  value: number;
  accent: string;
}

export default function QuickStat({ label, value, accent }: QuickStatProps) {
  const colorMap: Record<string, string> = {
    emerald: 'text-emerald-400',
    blue: 'text-blue-400',
    green: 'text-green-400',
    amber: 'text-amber-400',
    teal: 'text-teal-400',
    purple: 'text-purple-400',
    indigo: 'text-indigo-400',
    red: 'text-red-400',
  };

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${colorMap[accent] ?? 'text-gray-200'}`}>{value}</p>
    </div>
  );
}
