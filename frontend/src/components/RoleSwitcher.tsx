import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useRoleSimulation,
  ROLE_DEFINITIONS,
  type SimulationRole,
} from '../context/RoleSimulationContext';

const ROLES = Object.values(ROLE_DEFINITIONS);

export default function RoleSwitcher() {
  const { role, roleDef, setRole } = useRoleSimulation();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  function handleSelect(r: SimulationRole) {
    setRole(r);
    setOpen(false);
    if (r === 'adjuster') {
      navigate('/');
    } else {
      navigate('/simulate');
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
          role !== 'adjuster'
            ? `${roleDef.accentBg}/15 ${roleDef.accentText} ring-1 ${roleDef.accentRing}`
            : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
        }`}
      >
        <span className="text-base">{roleDef.icon}</span>
        <span className="flex-1 text-left truncate">{roleDef.label}</span>
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            data-testid="role-switcher-overlay"
            onClick={() => setOpen(false)}
            role="presentation"
          />
          <div className="absolute bottom-full left-0 right-0 mb-1 z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
            <div className="p-2 border-b border-gray-700/50">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 px-2">
                Simulate Role
              </p>
            </div>
            <div className="p-1">
              {ROLES.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => handleSelect(r.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                    role === r.id
                      ? `${r.accentBg}/15 ${r.accentText}`
                      : 'text-gray-400 hover:bg-gray-700/50 hover:text-gray-200'
                  }`}
                >
                  <span className="text-base">{r.icon}</span>
                  <div className="flex-1 text-left min-w-0">
                    <p className="font-medium truncate">{r.label}</p>
                    <p className="text-[11px] text-gray-500 truncate">{r.description}</p>
                  </div>
                  {role === r.id && (
                    <span className={`w-1.5 h-1.5 rounded-full ${r.accentBg}`} />
                  )}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
