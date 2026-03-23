import { useState } from 'react';
import { useClaims, useClaim, useClaimHistory } from '../../api/queries';
import { useQueryClient } from '@tanstack/react-query';
import PageHeader from '../../components/PageHeader';
import StatusBadge from '../../components/StatusBadge';
import EmptyState from '../../components/EmptyState';
import QuickStat from '../../components/QuickStat';
import MessagesTab from '../../components/MessagesTab';
import { ThirdPartyPortalOverview } from '../../components/thirdPartyPortal/ThirdPartyPortalOverview';
import { ThirdPartyPortalLiabilityPanel } from '../../components/thirdPartyPortal/ThirdPartyPortalLiabilityPanel';
import { formatDateTime } from '../../utils/date';
import { queryKeys } from '../../api/queries';
import { postClaimDispute } from '../../api/client';
import type { Claim, AuditEvent, FollowUpMessage } from '../../api/types';

/** Simulation uses adjuster dispute API; eligibility may differ from production third-party portal */
const SIMULATION_THIRD_PARTY_DISPUTABLE = ['open', 'settled'];

export default function ThirdPartyPortal() {
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const { data: claimsData, isLoading } = useClaims({ limit: 100 });
  const claims = claimsData?.claims ?? [];

  if (selectedClaimId) {
    return (
      <ThirdPartyClaimDetail
        claimId={selectedClaimId}
        onBack={() => setSelectedClaimId(null)}
      />
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="Cross-Carrier Claims"
        subtitle="Claims involving your policyholders or subrogation demands (simulation — adjuster API)"
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <QuickStat label="Total Claims" value={claims.length} accent="purple" />
        <QuickStat
          label="Active"
          value={claims.filter((c) => !['settled', 'closed', 'denied'].includes(c.status)).length}
          accent="blue"
        />
        <QuickStat
          label="Subrogation"
          value={claims.filter((c) => c.status === 'settled' || c.status === 'closed').length}
          accent="indigo"
        />
        <QuickStat
          label="Under Investigation"
          value={
            claims.filter((c) => c.status === 'under_investigation' || c.status === 'fraud_suspected')
              .length
          }
          accent="red"
        />
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 bg-gray-800/50 rounded-xl skeleton-shimmer" />
          ))}
        </div>
      ) : claims.length === 0 ? (
        <EmptyState
          icon="🏢"
          title="No cross-carrier claims"
          description="No claims involving your coverage found."
        />
      ) : (
        <div className="space-y-3">
          {claims.map((claim) => (
            <button
              key={claim.id}
              type="button"
              onClick={() => setSelectedClaimId(claim.id)}
              className="w-full text-left bg-gray-800/50 rounded-xl border border-gray-700/50 p-4 hover:bg-gray-800/70 hover:border-purple-500/20 transition-all group"
            >
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-3 min-w-0">
                  <p className="text-sm font-semibold text-gray-200 group-hover:text-purple-400 transition-colors truncate">
                    XC-{claim.id.slice(0, 8)}
                  </p>
                  <StatusBadge status={claim.status} />
                  {claim.claim_type && (
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-700/50 text-gray-400">
                      {claim.claim_type.replace(/_/g, ' ')}
                    </span>
                  )}
                </div>
                <span className="text-xs text-gray-500 shrink-0">
                  {formatDateTime(claim.created_at) ?? '—'}
                </span>
              </div>
              <div className="flex items-center gap-4 text-xs text-gray-400">
                <span>
                  {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}
                </span>
                {claim.payout_amount != null && (
                  <span className="text-purple-400 font-medium">
                    Demand: ${Number(claim.payout_amount).toLocaleString()}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ThirdPartyClaimDetail({ claimId, onBack }: { claimId: string; onBack: () => void }) {
  const { data: claim, isLoading, error } = useClaim(claimId);
  const { data: historyData } = useClaimHistory(claimId);
  const history = historyData?.history ?? [];
  const [activeTab, setActiveTab] = useState<'overview' | 'liability' | 'messages'>('overview');
  const queryClient = useQueryClient();

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
          <p className="text-sm text-red-400">
            {error instanceof Error ? error.message : 'Not found'}
          </p>
        </div>
      </div>
    );
  }

  const followUps = (claim.follow_up_messages ?? []).filter((m) => m.user_type === 'other');

  const tabs = [
    { key: 'overview' as const, label: 'Claim Overview' },
    { key: 'liability' as const, label: 'Liability & Subrogation' },
    { key: 'messages' as const, label: `Communications (${followUps.length})` },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-purple-400 transition-colors mb-3 group"
        >
          <svg
            className="w-4 h-4 transition-transform group-hover:-translate-x-0.5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 19l-7-7 7-7"
            />
          </svg>
          Cross-Carrier Claims
        </button>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-gray-100">XC-{claim.id.slice(0, 8)}</h1>
            <p className="text-sm text-gray-400 mt-1">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}
            </p>
          </div>
          <StatusBadge status={claim.status} />
        </div>
      </div>

      <div className="border-b border-gray-700/50">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 pb-3 pt-1 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-purple-500 text-purple-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-600'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="animate-fade-in" key={activeTab}>
        {activeTab === 'overview' && (
          <ThirdPartyPortalOverview claim={claim} history={history as AuditEvent[]} />
        )}
        {activeTab === 'liability' && (
          <ThirdPartyPortalLiabilityPanel
            claim={claim as Claim}
            disputableStatuses={[...SIMULATION_THIRD_PARTY_DISPUTABLE]}
            onSubmitDispute={async (evidence) => {
              const data = await postClaimDispute(claim.id, {
                dispute_type: 'liability_determination',
                dispute_description: `Third-party liability dispute: ${evidence}`,
                policyholder_evidence: null,
              });
              await queryClient.invalidateQueries({ queryKey: queryKeys.claim(claim.id) });
              await queryClient.invalidateQueries({ queryKey: queryKeys.claimHistory(claim.id) });
              return `Dispute filed. Resolution: ${String(data.resolution_type ?? 'pending')} — ${String(data.summary ?? '')}`;
            }}
          />
        )}
        {activeTab === 'messages' && (
          <MessagesTab
            followUps={followUps as FollowUpMessage[]}
            claimId={claim.id}
            accentColor="purple"
            senderLabel="From: Primary Carrier"
            emptyTitle="No communications"
            emptyDescription="No inter-carrier communications for this claim yet."
          />
        )}
      </div>
    </div>
  );
}
