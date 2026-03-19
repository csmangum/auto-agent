import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { portalApi } from '../api/portalClient';
import StatusBadge from '../components/StatusBadge';
import EmptyState from '../components/EmptyState';
import { formatDateTime } from '../utils/date';
import { usePortal } from '../context/usePortal';

export default function PortalClaimsList() {
  const navigate = useNavigate();
  const { logout, session } = usePortal();

  // Include a session identifier in the query key to prevent cross-session
  // cache leakage when a different claimant logs in within the same tab.
  const sessionKey =
    session?.token ??
    (session?.policyNumber && session?.vin
      ? `${session.policyNumber}:${session.vin}`
      : null) ??
    session?.email ??
    '';

  const { data, isLoading, error } = useQuery({
    queryKey: ['portal', 'claims', sessionKey],
    queryFn: () => portalApi.getClaims({ limit: 50 }),
  });

  const claims = (data?.claims ?? []) as Array<{
    id: string;
    status: string;
    claim_type?: string;
    vehicle_year?: number;
    vehicle_make?: string;
    vehicle_model?: string;
    incident_description?: string;
    estimated_damage?: number;
    payout_amount?: number;
    created_at?: string;
  }>;

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-gray-800 bg-gray-900/50 px-4 py-3 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-100">My Claims</h1>
        <button
          type="button"
          onClick={logout}
          className="text-sm text-gray-400 hover:text-gray-200 transition-colors"
        >
          Sign Out
        </button>
      </header>

      <main className="p-4 max-w-2xl mx-auto">
        {error && (
          <div className="mb-4 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error instanceof Error ? error.message : 'Failed to load claims'}
          </div>
        )}

        {isLoading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div
                key={i}
                className="h-20 bg-gray-800/50 rounded-xl animate-pulse"
              />
            ))}
          </div>
        ) : claims.length === 0 ? (
          <EmptyState
            icon="📋"
            title="No claims found"
            description="We couldn't find any claims matching your information."
          />
        ) : (
          <div className="space-y-3">
            {claims.map((claim) => (
              <button
                key={claim.id}
                type="button"
                onClick={() => navigate(`/portal/claims/${claim.id}`)}
                className="w-full text-left bg-gray-800/50 rounded-xl border border-gray-700/50 p-4 hover:bg-gray-800/70 hover:border-emerald-500/20 transition-all group"
              >
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="flex items-center gap-3 min-w-0">
                    <p className="text-sm font-semibold text-gray-200 group-hover:text-emerald-400 transition-colors truncate">
                      Claim {claim.id.slice(0, 8)}...
                    </p>
                    <StatusBadge status={claim.status} />
                  </div>
                  <span className="text-xs text-gray-500 shrink-0">
                    {formatDateTime(claim.created_at) ?? '—'}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-400">
                  <span>
                    {claim.vehicle_year} {claim.vehicle_make}{' '}
                    {claim.vehicle_model}
                  </span>
                  {claim.estimated_damage != null && (
                    <span className="text-gray-500">
                      Est. $
                      {Number(claim.estimated_damage).toLocaleString()}
                    </span>
                  )}
                  {claim.payout_amount != null && (
                    <span className="text-emerald-400 font-medium">
                      Payout: $
                      {Number(claim.payout_amount).toLocaleString()}
                    </span>
                  )}
                </div>
                {claim.incident_description && (
                  <p className="text-xs text-gray-500 mt-2 line-clamp-1">
                    {claim.incident_description}
                  </p>
                )}
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
