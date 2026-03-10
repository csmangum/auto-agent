import { useNavigate } from 'react-router-dom';
import StatusBadge from './StatusBadge';
import TypeBadge from './TypeBadge';
import EmptyState from './EmptyState';
import { formatDate } from '../utils/date';
import type { Claim } from '../api/types';

interface ClaimTableProps {
  claims: Claim[];
  compact?: boolean;
}

export default function ClaimTable({ claims, compact = false }: ClaimTableProps) {
  const navigate = useNavigate();

  if (!claims || claims.length === 0) {
    return (
      <EmptyState
        icon="📋"
        title="No claims found"
        description="There are no claims matching your current filters."
        actionLabel="Submit a Claim"
        actionTo="/claims/new"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700/50 text-left text-gray-500 text-xs uppercase tracking-wider">
            <th className="px-4 py-3 font-medium">Claim ID</th>
            <th className="px-4 py-3 font-medium">Policy</th>
            {!compact && <th className="px-4 py-3 font-medium">VIN</th>}
            <th className="px-4 py-3 font-medium">Type</th>
            <th className="px-4 py-3 font-medium">Status</th>
            {!compact && <th className="px-4 py-3 font-medium">Incident Date</th>}
            <th className="px-4 py-3 font-medium">Created</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {claims.map((claim) => (
            <tr
              key={claim.id}
              onClick={() => navigate(`/claims/${claim.id}`)}
              className="hover:bg-gray-800/50 cursor-pointer transition-colors group"
            >
              <td className="px-4 py-3 font-mono text-blue-400 font-medium group-hover:text-blue-300">
                {claim.id}
              </td>
              <td className="px-4 py-3 text-gray-300">{claim.policy_number || '—'}</td>
              {!compact && (
                <td className="px-4 py-3 font-mono text-gray-500 text-xs">
                  {claim.vin ? `${claim.vin.slice(0, 8)}…` : '—'}
                </td>
              )}
              <td className="px-4 py-3">
                <TypeBadge type={claim.claim_type} />
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={claim.status} />
              </td>
              {!compact && (
                <td className="px-4 py-3 text-gray-400">{claim.incident_date || '—'}</td>
              )}
              <td className="px-4 py-3 text-gray-500 text-xs">
                {formatDate(claim.created_at) ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
