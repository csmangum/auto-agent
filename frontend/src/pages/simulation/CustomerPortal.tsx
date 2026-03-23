import { useState } from 'react';
import { useClaims, useClaim, useClaimHistory } from '../../api/queries';
import ClaimantPortalSignpost from '../../components/ClaimantPortalSignpost';
import PageHeader from '../../components/PageHeader';
import StatusBadge from '../../components/StatusBadge';
import EmptyState from '../../components/EmptyState';
import QuickStat from '../../components/QuickStat';
import { formatDateTime } from '../../utils/date';
import CustomerClaimView from './CustomerClaimView';

export default function CustomerPortal() {
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const { data: claimsData, isLoading } = useClaims({ limit: 50 });
  const claims = claimsData?.claims ?? [];

  if (selectedClaimId) {
    return (
      <CustomerClaimDetail
        claimId={selectedClaimId}
        onBack={() => setSelectedClaimId(null)}
      />
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="My Claims"
        subtitle="Track the status of your insurance claims"
      />

      <ClaimantPortalSignpost />

      {/* Quick stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <QuickStat label="Total Claims" value={claims.length} accent="emerald" />
        <QuickStat label="In Progress" value={claims.filter((c) => ['pending', 'processing', 'open'].includes(c.status)).length} accent="blue" />
        <QuickStat label="Settled" value={claims.filter((c) => c.status === 'settled').length} accent="green" />
        <QuickStat label="Needs Response" value={claims.filter((c) => c.status === 'pending_info').length} accent="amber" />
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 bg-gray-800/50 rounded-xl skeleton-shimmer" />
          ))}
        </div>
      ) : claims.length === 0 ? (
        <EmptyState
          icon="📋"
          title="No claims yet"
          description="You haven't filed any insurance claims."
        />
      ) : (
        <div className="space-y-3">
          {claims.map((claim) => (
            <button
              key={claim.id}
              type="button"
              onClick={() => setSelectedClaimId(claim.id)}
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
                <span>{claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}</span>
                {claim.estimated_damage != null && (
                  <span className="text-gray-500">
                    Est. ${Number(claim.estimated_damage).toLocaleString()}
                  </span>
                )}
                {claim.payout_amount != null && (
                  <span className="text-emerald-400 font-medium">
                    Payout: ${Number(claim.payout_amount).toLocaleString()}
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
    </div>
  );
}

function CustomerClaimDetail({ claimId, onBack }: { claimId: string; onBack: () => void }) {
  const { data: claim, isLoading, error } = useClaim(claimId);
  const { data: historyData } = useClaimHistory(claimId);
  const history = historyData?.history ?? [];

  if (isLoading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="h-8 bg-gray-700/50 rounded w-48 skeleton-shimmer" />
        <div className="h-64 bg-gray-800/50 rounded-xl skeleton-shimmer" />
      </div>
    );
  }

  if (error || !claim) {
    return (
      <div className="space-y-4 animate-fade-in">
        <PageHeader title="Claim" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Claim not found'}</p>
        </div>
      </div>
    );
  }

  return (
    <CustomerClaimView
      claim={claim}
      history={history}
      onBack={onBack}
    />
  );
}
