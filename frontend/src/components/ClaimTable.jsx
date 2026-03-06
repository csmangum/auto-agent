import { useNavigate } from 'react-router-dom';
import StatusBadge from './StatusBadge';

export default function ClaimTable({ claims, compact = false }) {
  const navigate = useNavigate();

  if (!claims || claims.length === 0) {
    return <p className="text-gray-500 text-sm py-4">No claims found.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left text-gray-500 text-xs uppercase tracking-wider">
            <th className="px-4 py-3 font-medium">Claim ID</th>
            <th className="px-4 py-3 font-medium">Policy</th>
            {!compact && <th className="px-4 py-3 font-medium">VIN</th>}
            <th className="px-4 py-3 font-medium">Type</th>
            <th className="px-4 py-3 font-medium">Status</th>
            {!compact && <th className="px-4 py-3 font-medium">Incident Date</th>}
            <th className="px-4 py-3 font-medium">Created</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {claims.map((claim) => (
            <tr
              key={claim.id}
              onClick={() => navigate(`/claims/${claim.id}`)}
              className="hover:bg-gray-50 cursor-pointer transition-colors"
            >
              <td className="px-4 py-3 font-mono text-blue-600 font-medium">{claim.id}</td>
              <td className="px-4 py-3 text-gray-700">{claim.policy_number || '—'}</td>
              {!compact && (
                <td className="px-4 py-3 font-mono text-gray-500 text-xs">
                  {claim.vin ? `${claim.vin.slice(0, 8)}...` : '—'}
                </td>
              )}
              <td className="px-4 py-3">
                <span className="text-gray-700">
                  {claim.claim_type ? claim.claim_type.replace(/_/g, ' ') : 'unclassified'}
                </span>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={claim.status} />
              </td>
              {!compact && (
                <td className="px-4 py-3 text-gray-500">{claim.incident_date || '—'}</td>
              )}
              <td className="px-4 py-3 text-gray-400 text-xs">
                {claim.created_at ? new Date(claim.created_at).toLocaleDateString() : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
