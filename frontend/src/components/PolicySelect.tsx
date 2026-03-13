import { useState, useRef, useEffect } from 'react';
import type { PolicyWithVehicles } from '../api/client';

interface PolicySelectProps {
  policies: PolicyWithVehicles[];
  value: string;
  onChange: (policyNumber: string) => void;
  id?: string;
  required?: boolean;
  className?: string;
  placeholder?: string;
}

export default function PolicySelect({
  policies,
  value,
  onChange,
  id = 'policy_number',
  required,
  className = '',
  placeholder = 'Select a policy…',
}: PolicySelectProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selected = policies.find((p) => p.policy_number === value);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [open]);

  const formatCell = (val: number | undefined) =>
    val != null ? `${(val / 1000).toFixed(0)}k` : '—';
  const formatDed = (p: PolicyWithVehicles) => {
    const d = p.collision_deductible ?? p.comprehensive_deductible;
    return d != null ? `$${d}` : '—';
  };

  return (
    <div ref={containerRef} className="relative">
      <input type="hidden" name={id} value={value} required={required} />
      <button
        type="button"
        id={id}
        onClick={() => setOpen((o) => !o)}
        className={`w-full text-left border border-gray-700 rounded-lg px-3 py-2 bg-gray-800 text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors ${className}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-required={required}
      >
        {selected ? (
          <span className="font-medium">{selected.policy_number}</span>
        ) : (
          <span className="text-gray-500">{placeholder}</span>
        )}
      </button>
      {open && (
        <div
          className="absolute z-50 mt-1 w-full min-w-[28rem] rounded-lg border border-gray-600 bg-gray-800 shadow-xl overflow-hidden"
          role="listbox"
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 bg-gray-900/80">
                <th className="px-3 py-2 text-left font-medium text-gray-400">Policy</th>
                <th className="px-3 py-2 text-right font-medium text-gray-400">Vehicles</th>
                <th className="px-3 py-2 text-right font-medium text-gray-400">BI</th>
                <th className="px-3 py-2 text-right font-medium text-gray-400">PD</th>
                <th className="px-3 py-2 text-right font-medium text-gray-400">Ded</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => {
                const vc = p.vehicle_count ?? p.vehicles.length;
                const liab = p.liability_limits;
                const isSelected = p.policy_number === value;
                return (
                  <tr
                    key={p.policy_number}
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      onChange(p.policy_number);
                      setOpen(false);
                    }}
                    className={`border-b border-gray-700/50 cursor-pointer transition-colors ${
                      isSelected ? 'bg-blue-500/20' : 'hover:bg-gray-700/50'
                    }`}
                  >
                    <td className="px-3 py-2 font-medium text-gray-200">{p.policy_number}</td>
                    <td className="px-3 py-2 text-right text-gray-300">{vc}</td>
                    <td className="px-3 py-2 text-right text-gray-300 tabular-nums">
                      {formatCell(liab?.bi_per_accident)}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-300 tabular-nums">
                      {formatCell(liab?.pd_per_accident)}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-300 tabular-nums">
                      {formatDed(p)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
