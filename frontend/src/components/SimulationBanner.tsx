import { useRoleSimulation } from '../context/RoleSimulationContext';

const ACCENT_STYLES: Record<string, string> = {
  emerald: 'bg-emerald-600/10 border-emerald-500/30 text-emerald-400',
  amber: 'bg-amber-600/10 border-amber-500/30 text-amber-400',
  purple: 'bg-purple-600/10 border-purple-500/30 text-purple-400',
};

export default function SimulationBanner() {
  const { isSimulating, roleDef, exitSimulation } = useRoleSimulation();

  if (!isSimulating) return null;

  const style = ACCENT_STYLES[roleDef.accent] ?? ACCENT_STYLES.emerald;

  return (
    <div className={`border-b px-4 py-2 flex items-center justify-between gap-3 ${style}`}>
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm">{roleDef.icon}</span>
        <p className="text-xs font-medium truncate">
          Simulating: <span className="font-semibold">{roleDef.label}</span>
          <span className="text-gray-500 ml-2 hidden sm:inline">{roleDef.description}</span>
        </p>
      </div>
      <button
        type="button"
        onClick={exitSimulation}
        className="shrink-0 text-xs px-2.5 py-1 rounded-md bg-gray-800/50 hover:bg-gray-700/50 text-gray-300 hover:text-white transition-colors"
      >
        Exit
      </button>
    </div>
  );
}
