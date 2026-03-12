import { useState } from 'react';
import { useClaims, useClaim, useClaimHistory } from '../../api/queries';
import { useQueryClient } from '@tanstack/react-query';
import PageHeader from '../../components/PageHeader';
import StatusBadge from '../../components/StatusBadge';
import EmptyState from '../../components/EmptyState';
import QuickStat from '../../components/QuickStat';
import MessagesTab from '../../components/MessagesTab';
import { formatDateTime } from '../../utils/date';
import { queryKeys } from '../../api/queries';
import { postClaimDispute } from '../../api/client';
import type { Claim, AuditEvent, FollowUpMessage } from '../../api/types';

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
        subtitle="Claims involving your policyholders or subrogation demands"
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <QuickStat label="Total Claims" value={claims.length} accent="purple" />
        <QuickStat label="Active" value={claims.filter((c) => !['settled', 'closed', 'denied'].includes(c.status)).length} accent="blue" />
        <QuickStat label="Subrogation" value={claims.filter((c) => c.status === 'settled' || c.status === 'closed').length} accent="indigo" />
        <QuickStat label="Under Investigation" value={claims.filter((c) => c.status === 'under_investigation' || c.status === 'fraud_suspected').length} accent="red" />
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
                <span>{claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}</span>
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
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Not found'}</p>
        </div>
      </div>
    );
  }

  const followUps = (claim.follow_up_messages ?? []).filter(
    (m) => m.user_type === 'other'
  );

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
          <svg className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
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
        {activeTab === 'overview' && <OverviewTab claim={claim} history={history} />}
        {activeTab === 'liability' && <LiabilityTab claim={claim} />}
        {activeTab === 'messages' && (
          <MessagesTab
            followUps={followUps}
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

function OverviewTab({ claim, history }: { claim: Claim; history: AuditEvent[] }) {
  const relevantHistory = history.filter((e) =>
    e.action.includes('status') || e.action.includes('settled') || e.action.includes('subrogation')
  );

  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Claim Summary</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Vehicle</p>
            <p className="text-sm text-gray-300 mt-0.5">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Incident Date</p>
            <p className="text-sm text-gray-300 mt-0.5">{claim.incident_date ?? '—'}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Status</p>
            <p className="text-sm text-gray-300 mt-0.5 capitalize">{claim.status.replace(/_/g, ' ')}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Type</p>
            <p className="text-sm text-gray-300 mt-0.5 capitalize">{(claim.claim_type ?? '—').replace(/_/g, ' ')}</p>
          </div>
          {claim.payout_amount != null && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">Demand Amount</p>
              <p className="text-sm text-purple-400 font-semibold font-mono mt-0.5">
                ${Number(claim.payout_amount).toLocaleString()}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-purple-500/50">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Incident Description</h3>
        <p className="text-sm text-gray-400 leading-relaxed">
          {claim.incident_description ?? 'No description available.'}
        </p>
      </div>

      {relevantHistory.length > 0 && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Key Events</h3>
          <div className="space-y-0">
            {relevantHistory.map((event, i) => (
              <div key={event.id ?? i} className="flex gap-3 pb-4 last:pb-0">
                <div className="flex flex-col items-center">
                  <div className="w-2.5 h-2.5 rounded-full bg-purple-500/50 ring-2 ring-purple-500/20 mt-1" />
                  {i < relevantHistory.length - 1 && <div className="w-px flex-1 bg-gray-700/50 mt-1" />}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-300">
                    {event.new_status ? `Status: ${event.new_status.replace(/_/g, ' ')}` : event.action.replace(/_/g, ' ')}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{formatDateTime(event.created_at) ?? ''}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function LiabilityTab({ claim }: { claim: Claim }) {
  const [evidence, setEvidence] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const canDispute = ['settled', 'dispute_resolved', 'closed'].includes(claim.status);

  async function handleSubmitEvidence(e: React.FormEvent) {
    e.preventDefault();
    if (!evidence.trim()) return;
    setSubmitting(true);
    setResult(null);
    try {
      const data = await postClaimDispute(claim.id, {
        dispute_type: 'liability_determination',
        dispute_description: `Third-party liability dispute: ${evidence.trim()}`,
        policyholder_evidence: null,
      });
      setResult(`Dispute filed. Resolution: ${data.resolution_type ?? 'pending'} — ${data.summary ?? ''}`);
      setEvidence('');
      
      await queryClient.invalidateQueries({ queryKey: queryKeys.claim(claim.id) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.claimHistory(claim.id) });
    } catch (err) {
      setResult(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Liability & Subrogation Status</h3>
        <p className="text-xs text-gray-500 mb-4">
          Current claim status and subrogation demand information for cross-carrier resolution.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Claim Status</p>
            <p className="text-sm text-gray-300 capitalize mt-0.5">{claim.status.replace(/_/g, ' ')}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Claim Type</p>
            <p className="text-sm text-gray-300 capitalize mt-0.5">{(claim.claim_type ?? '—').replace(/_/g, ' ')}</p>
          </div>
          {claim.payout_amount != null && (
            <div className="md:col-span-2">
              <p className="text-xs text-gray-500 uppercase tracking-wider">Subrogation Demand Amount</p>
              <p className="text-lg text-purple-400 font-bold font-mono mt-0.5">
                ${Number(claim.payout_amount).toLocaleString()}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-1">Dispute Liability Determination</h3>
        <p className="text-xs text-gray-500 mb-4">
          Submit evidence or arguments challenging the liability determination or subrogation demand.
        </p>

        {!canDispute ? (
          <div className="bg-gray-900/50 rounded-lg p-4 text-sm text-gray-500">
            Liability disputes can only be filed on settled or resolved claims.
            Current status: "{claim.status.replace(/_/g, ' ')}"
          </div>
        ) : (
          <>
            {result && (
              <div className={`text-sm px-4 py-2 rounded-lg mb-4 ${
                result.startsWith('Error') ? 'bg-red-500/10 text-red-400' : 'bg-purple-500/10 text-purple-400'
              }`}>
                {result}
              </div>
            )}

            <form onSubmit={handleSubmitEvidence} className="space-y-4">
              <textarea
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
                placeholder="Describe your liability position and supporting evidence (police reports, witness statements, dash cam footage, etc.)..."
                rows={4}
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-purple-500/40 resize-none"
                required
              />
              <button
                type="submit"
                disabled={submitting || !evidence.trim()}
                className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-500 disabled:opacity-50 transition-colors"
              >
                {submitting ? 'Submitting...' : 'Submit Liability Dispute'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
