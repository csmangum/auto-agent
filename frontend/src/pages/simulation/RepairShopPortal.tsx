import { useState } from 'react';
import { useClaims, useClaim } from '../../api/queries';
import { useQueryClient } from '@tanstack/react-query';
import PageHeader from '../../components/PageHeader';
import StatusBadge from '../../components/StatusBadge';
import EmptyState from '../../components/EmptyState';
import QuickStat from '../../components/QuickStat';
import MessagesTab from '../../components/MessagesTab';
import { formatDateTime } from '../../utils/date';
import { queryKeys } from '../../api/queries';
import { postClaimSupplemental } from '../../api/client';
import { useClaimRepairStatus, usePostClaimRepairStatus } from '../../api/queries';
import type { Claim, FollowUpMessage } from '../../api/types';

const REPAIR_STATUS_ORDER = [
  'received',
  'disassembly',
  'parts_ordered',
  'repair',
  'paint',
  'reassembly',
  'qa',
  'ready',
] as const;

const REPAIR_RELEVANT_STATUSES = new Set([
  'partial_loss', 'open', 'settled', 'processing', 'pending',
  'needs_review', 'pending_info',
]);

export default function RepairShopPortal() {
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const { data: claimsData, isLoading } = useClaims({ limit: 100 });
  const repairJobs = (claimsData?.claims ?? []).filter(
    (c) => c.claim_type === 'partial_loss' || REPAIR_RELEVANT_STATUSES.has(c.status)
  );

  if (selectedClaimId) {
    return (
      <RepairJobDetail
        claimId={selectedClaimId}
        onBack={() => setSelectedClaimId(null)}
      />
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="Repair Jobs"
        subtitle="Manage vehicle repairs and submit supplemental reports"
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <QuickStat label="Active Jobs" value={repairJobs.filter((c) => !['settled', 'closed', 'denied'].includes(c.status)).length} accent="amber" />
        <QuickStat label="Partial Loss" value={repairJobs.filter((c) => c.claim_type === 'partial_loss').length} accent="teal" />
        <QuickStat label="Awaiting Auth" value={repairJobs.filter((c) => c.status === 'needs_review' || c.status === 'pending').length} accent="blue" />
        <QuickStat label="Completed" value={repairJobs.filter((c) => c.status === 'settled' || c.status === 'closed').length} accent="green" />
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 bg-gray-800/50 rounded-xl skeleton-shimmer" />
          ))}
        </div>
      ) : repairJobs.length === 0 ? (
        <EmptyState
          icon="🔧"
          title="No repair jobs"
          description="No claims have been assigned for repair."
        />
      ) : (
        <div className="space-y-3">
          {repairJobs.map((claim) => (
            <button
              key={claim.id}
              type="button"
              onClick={() => setSelectedClaimId(claim.id)}
              className="w-full text-left bg-gray-800/50 rounded-xl border border-gray-700/50 p-4 hover:bg-gray-800/70 hover:border-amber-500/20 transition-all group"
            >
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-3 min-w-0">
                  <p className="text-sm font-semibold text-gray-200 group-hover:text-amber-400 transition-colors truncate">
                    RO-{claim.id.slice(0, 8)}
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
                <span className="text-gray-600">VIN: {claim.vin}</span>
              </div>
              {claim.damage_description && (
                <p className="text-xs text-gray-500 mt-2 line-clamp-1">
                  {claim.damage_description}
                </p>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function RepairJobDetail({ claimId, onBack }: { claimId: string; onBack: () => void }) {
  const { data: claim, isLoading, error } = useClaim(claimId);
  const [activeTab, setActiveTab] = useState<'details' | 'progress' | 'supplement' | 'messages'>('details');

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
        <PageHeader title="Repair Job" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Not found'}</p>
        </div>
      </div>
    );
  }

  const followUps = (claim.follow_up_messages ?? []).filter(
    (m) => m.user_type === 'repair_shop'
  );
  const canSupplement = claim.claim_type === 'partial_loss' &&
    ['processing', 'settled'].includes(claim.status);
  const canUpdateProgress = claim.claim_type === 'partial_loss';

  const tabs = [
    { key: 'details' as const, label: 'Vehicle & Damage' },
    { key: 'progress' as const, label: 'Repair Progress' },
    { key: 'supplement' as const, label: 'Supplemental' },
    { key: 'messages' as const, label: `Messages (${followUps.length})` },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-amber-400 transition-colors mb-3 group"
        >
          <svg className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Repair Jobs
        </button>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-gray-100">
              RO-{claim.id.slice(0, 8)}
            </h1>
            <p className="text-sm text-gray-400 mt-1">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model} — VIN: {claim.vin}
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
                  ? 'border-amber-500 text-amber-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-600'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="animate-fade-in" key={activeTab}>
        {activeTab === 'details' && <VehicleDamageTab claim={claim} />}
        {activeTab === 'progress' && (
          <RepairProgressTab claimId={claim.id} canUpdate={canUpdateProgress} />
        )}
        {activeTab === 'supplement' && (
          <SupplementalTab claimId={claim.id} canSupplement={canSupplement} status={claim.status} claimType={claim.claim_type} />
        )}
        {activeTab === 'messages' && (
          <MessagesTab
            followUps={followUps}
            claimId={claim.id}
            accentColor="amber"
            senderLabel="From: Insurance Carrier"
            emptyTitle="No messages"
            emptyDescription="No messages from the insurance carrier for this repair."
          />
        )}
      </div>
    </div>
  );
}

function RepairProgressTab({ claimId, canUpdate }: { claimId: string; canUpdate: boolean }) {
  const { data, isLoading, isError, error } = useClaimRepairStatus(claimId);
  const postStatus = usePostClaimRepairStatus(claimId);
  const latest = data?.latest;
  const history = data?.history ?? [];

  const currentIdx = latest
    ? REPAIR_STATUS_ORDER.indexOf(latest.status as (typeof REPAIR_STATUS_ORDER)[number])
    : -1;

  async function handleStatusChange(status: string) {
    if (!canUpdate || postStatus.isPending) return;
    try {
      await postStatus.mutateAsync({ status });
    } catch {
      // Error shown via postStatus.isError below
    }
  }

  if (isLoading) {
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <div className="h-32 bg-gray-700/50 rounded skeleton-shimmer" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <p className="text-sm text-red-400">
          {error instanceof Error ? error.message : 'Failed to load repair status'}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Repair Progress</h3>
        <p className="text-xs text-gray-500 mb-4">
          Track repair stages: received → disassembly → parts ordered → repair → paint → reassembly → QA → ready.
        </p>

        <div className="flex flex-wrap gap-2 mb-4">
          {REPAIR_STATUS_ORDER.map((status, idx) => {
            const isPast = currentIdx > idx;
            const isCurrent = latest?.status === status;
            return (
              <button
                key={status}
                type="button"
                onClick={() => canUpdate && handleStatusChange(status)}
                disabled={!canUpdate || postStatus.isPending}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  isCurrent
                    ? 'bg-amber-600 text-white'
                    : isPast
                      ? 'bg-gray-600/50 text-gray-400'
                      : 'bg-gray-700/50 text-gray-500 hover:bg-gray-600/50'
                } ${!canUpdate ? 'cursor-default' : ''}`}
              >
                {status.replace(/_/g, ' ')}
              </button>
            );
          })}
        </div>

        {postStatus.isError && (
          <p className="text-sm text-red-400 mb-2">
            {postStatus.error instanceof Error
              ? postStatus.error.message
              : 'Failed to update repair status'}
          </p>
        )}

        {latest && (
          <div className="text-xs text-gray-500">
            Current: {latest.status === 'paused_supplement'
              ? 'Repair paused – supplemental pending'
              : latest.status.replace(/_/g, ' ')}
            {latest.status_updated_at && ` • ${formatDateTime(latest.status_updated_at) ?? ''}`}
            {latest.notes && ` • ${latest.notes}`}
            {data?.cycle_time_days != null && latest.status === 'ready' && (
              <span className="block mt-1 text-amber-400/80">
                Cycle time: {data.cycle_time_days} days
              </span>
            )}
          </div>
        )}

        {!latest && canUpdate && (
          <p className="text-xs text-gray-500">Click a stage to record progress.</p>
        )}
      </div>

      {history.length > 0 && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Status History</h3>
          <ul className="space-y-2 max-h-48 overflow-y-auto">
            {[...history].reverse().map((h) => (
              <li key={h.id} className="flex justify-between text-xs text-gray-400">
                <span>{h.status.replace(/_/g, ' ')}</span>
                <span>{formatDateTime(h.status_updated_at) ?? '—'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function VehicleDamageTab({ claim }: { claim: Claim }) {
  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Vehicle Information</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Vehicle</p>
            <p className="text-sm text-gray-300 mt-0.5">{claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">VIN</p>
            <p className="text-sm text-gray-300 font-mono mt-0.5">{claim.vin}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Incident Date</p>
            <p className="text-sm text-gray-300 mt-0.5">{claim.incident_date ?? '—'}</p>
          </div>
          {claim.estimated_damage != null && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">Insurance Estimate</p>
              <p className="text-sm text-gray-200 font-mono mt-0.5">${Number(claim.estimated_damage).toLocaleString()}</p>
            </div>
          )}
        </div>
      </div>

      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-amber-500/50">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Damage Description</h3>
        <p className="text-sm text-gray-400 leading-relaxed">
          {claim.damage_description ?? 'No damage description provided.'}
        </p>
      </div>

      {claim.incident_description && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Incident Details</h3>
          <p className="text-sm text-gray-400 leading-relaxed">{claim.incident_description}</p>
        </div>
      )}
    </div>
  );
}

function SupplementalTab({ claimId, canSupplement, status, claimType }: {
  claimId: string;
  canSupplement: boolean;
  status: string;
  claimType?: string;
}) {
  const [form, setForm] = useState({
    supplemental_damage_description: '',
    reported_by: 'shop' as 'shop' | 'adjuster' | 'policyholder',
  });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const queryClient = useQueryClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.supplemental_damage_description.trim()) return;
    setSubmitting(true);
    setResult(null);
    try {
      const data = await postClaimSupplemental(claimId, {
        supplemental_damage_description: form.supplemental_damage_description.trim(),
        reported_by: form.reported_by,
      });
      setResult(
        `Supplemental filed. Amount: $${data.supplemental_amount?.toLocaleString() ?? 'TBD'} — ${data.summary ?? ''}`
      );
      setForm({ supplemental_damage_description: '', reported_by: 'shop' });
      
      await queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.claimHistory(claimId) });
    } catch (err) {
      setResult(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (!canSupplement) {
    const reason = claimType !== 'partial_loss'
      ? 'Supplementals only apply to partial loss claims.'
      : `Supplementals cannot be filed when the claim is "${status.replace(/_/g, ' ')}".`;
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <EmptyState icon="📝" title="Supplemental not available" description={reason} />
      </div>
    );
  }

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-1">Submit Supplemental Damage Report</h3>
      <p className="text-xs text-gray-500 mb-4">
        Report additional damage discovered during disassembly or repair that was not included in the original estimate.
      </p>

      {result && (
        <div className={`text-sm px-4 py-2 rounded-lg mb-4 ${
          result.startsWith('Error') ? 'bg-red-500/10 text-red-400' : 'bg-amber-500/10 text-amber-400'
        }`}>
          {result}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Additional Damage Description</label>
          <textarea
            value={form.supplemental_damage_description}
            onChange={(e) => setForm((f) => ({ ...f, supplemental_damage_description: e.target.value }))}
            placeholder="Describe additional damage found during teardown (e.g., hidden structural damage, additional panels needing replacement)..."
            rows={5}
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-amber-500/40 resize-none"
            required
          />
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Reported By</label>
          <select
            value={form.reported_by}
            onChange={(e) => setForm((f) => ({ ...f, reported_by: e.target.value as 'shop' | 'adjuster' | 'policyholder' }))}
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-amber-500/40"
          >
            <option value="shop">Repair Shop</option>
            <option value="adjuster">Field Adjuster</option>
            <option value="policyholder">Policyholder</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={submitting || !form.supplemental_damage_description.trim()}
          className="px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-500 disabled:opacity-50 transition-colors"
        >
          {submitting ? 'Submitting...' : 'Submit Supplemental'}
        </button>
      </form>
    </div>
  );
}
