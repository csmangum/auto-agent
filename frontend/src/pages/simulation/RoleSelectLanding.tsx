import { useNavigate } from 'react-router-dom';
import PageHeader from '../../components/PageHeader';
import {
  useRoleSimulation,
  ROLE_DEFINITIONS,
  type SimulationRole,
} from '../../context/RoleSimulationContext';

const SIMULATABLE_ROLES = (
  Object.values(ROLE_DEFINITIONS).filter((r) => r.id !== 'adjuster')
);

const ACCENT_MAP: Record<string, { card: string; hover: string; border: string }> = {
  emerald: {
    card: 'hover:bg-emerald-600/5',
    hover: 'group-hover:text-emerald-400',
    border: 'hover:border-emerald-500/30',
  },
  amber: {
    card: 'hover:bg-amber-600/5',
    hover: 'group-hover:text-amber-400',
    border: 'hover:border-amber-500/30',
  },
  purple: {
    card: 'hover:bg-purple-600/5',
    hover: 'group-hover:text-purple-400',
    border: 'hover:border-purple-500/30',
  },
};

const ROLE_CAPABILITIES: Record<SimulationRole, string[]> = {
  adjuster: [],
  customer: [
    'File new insurance claims',
    'Track claim status and timeline',
    'Respond to follow-up messages',
    'File disputes on settled claims',
    'View settlement offers and denial letters',
  ],
  repair_shop: [
    'View assigned repair jobs',
    'Submit supplemental damage reports',
    'Respond to follow-up messages',
    'View repair authorizations and estimates',
    'Track parts and labor details',
  ],
  third_party: [
    'View subrogation demands',
    'Respond to liability determinations',
    'Submit third-party claims',
    'Provide counter-evidence',
    'Track cross-carrier communications',
  ],
};

export default function RoleSelectLanding() {
  const { setRole } = useRoleSimulation();
  const navigate = useNavigate();

  function handleSelect(roleId: SimulationRole) {
    setRole(roleId);
    navigate('/simulate');
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <PageHeader
        title="Role Simulation"
        subtitle="Experience the claims system from different perspectives. Select a role to begin."
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {SIMULATABLE_ROLES.map((r) => {
          const accents = ACCENT_MAP[r.accent] ?? ACCENT_MAP.emerald;
          const capabilities = ROLE_CAPABILITIES[r.id];
          return (
            <button
              key={r.id}
              type="button"
              onClick={() => handleSelect(r.id)}
              className={`group text-left bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 transition-all duration-200 ${accents.card} ${accents.border}`}
            >
              <div className="flex items-center gap-3 mb-4">
                <div className={`w-10 h-10 rounded-lg ${r.accentBg} flex items-center justify-center text-white text-lg shadow-lg`}>
                  {r.icon}
                </div>
                <div>
                  <h3 className={`text-base font-semibold text-gray-200 ${accents.hover} transition-colors`}>
                    {r.label}
                  </h3>
                  <p className="text-xs text-gray-500">{r.description}</p>
                </div>
              </div>

              <ul className="space-y-2">
                {capabilities.map((cap) => (
                  <li key={cap} className="flex items-start gap-2 text-xs text-gray-400">
                    <svg className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${r.accentText}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    {cap}
                  </li>
                ))}
              </ul>

              <div className={`mt-4 pt-3 border-t border-gray-700/50 text-xs font-medium ${r.accentText} opacity-0 group-hover:opacity-100 transition-opacity`}>
                Enter simulation →
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
