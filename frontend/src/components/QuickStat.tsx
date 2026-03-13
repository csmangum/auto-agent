import { QUICK_STAT_COLOR_MAP, type QuickStatAccent } from '../utils/theme';

export type { QuickStatAccent };

interface QuickStatProps {
  label: string;
  value: number;
  accent: QuickStatAccent;
}

export default function QuickStat({ label, value, accent }: QuickStatProps) {
  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${QUICK_STAT_COLOR_MAP[accent] ?? 'text-gray-200'}`}>{value}</p>
    </div>
  );
}
