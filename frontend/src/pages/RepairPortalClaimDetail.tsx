import { useState } from 'react';
import { useNavigate, useParams, Navigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRepairPortal } from '../context/useRepairPortal';
import { repairPortalApi } from '../api/repairPortalClient';
import StatusBadge from '../components/StatusBadge';
import EmptyState from '../components/EmptyState';
import MessagesTab from '../components/MessagesTab';
import { formatDateTime } from '../utils/date';
import type { Claim, FollowUpMessage } from '../api/types';
import { getErrorMessage } from '../utils/errorMessage';

const REPAIR_STATUS_ORDER = [
  'received',
  'disassembly',
  'parts_ordered',
  'repair',
  'paused_supplement',
  'paint',
  'reassembly',
  'qa',
  'ready',
] as const;

const qk = {
  claim: (id: string) => ['repair-portal', 'claim', id] as const,
  repair: (id: string) => ['repair-portal', 'repair-status', id] as const,
};

export default function RepairPortalClaimDetail() {
  const { claimId: paramClaimId } = useParams<{ claimId: string }>();
  const navigate = useNavigate();
  const { session, logout } = useRepairPortal();
  const claimId = paramClaimId ?? '';

  if (!session?.claimId || !session?.token) {
    return <Navigate to="/repair-portal/login" replace />;
  }

  if (claimId !== session.claimId) {
    return <Navigate to={`/repair-portal/claims/${session.claimId}`} replace />;
  }

  return (
    <RepairPortalClaimBody
      claimId={claimId}
      onLogout={() => {
        logout();
        navigate('/repair-portal/login', { replace: true });
      }}
    />
  );
}

function RepairPortalClaimBody({
  claimId,
  onLogout,
}: {
  claimId: string;
  onLogout: () => void;
}) {
  const [activeTab, setActiveTab] = useState<
    'details' | 'progress' | 'supplement' | 'messages'
  >('details');
  const queryClient = useQueryClient();

  const { data: claimRaw, isLoading, error } = useQuery({
    queryKey: qk.claim(claimId),
    queryFn: () => repairPortalApi.getClaim(claimId),
  });

  const claim = claimRaw as Claim | undefined;
  const followUps = (claim?.follow_up_messages ?? []) as FollowUpMessage[];
  const shopMessages = followUps.filter((m) => m.user_type === 'repair_shop');
  const canSupplement =
    claim?.claim_type === 'partial_loss' &&
    ['processing', 'settled'].includes(claim?.status ?? '');
  const canUpdateProgress = claim?.claim_type === 'partial_loss';

  const tabs = [
    { key: 'details' as const, label: 'Vehicle & Damage' },
    { key: 'progress' as const, label: 'Repair Progress' },
    { key: 'supplement' as const, label: 'Supplemental' },
    { key: 'messages' as const, label: `Messages (${shopMessages.length})` },
  ];

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 p-6">
        <div className="max-w-4xl mx-auto space-y-4 animate-fade-in">
          <div className="h-8 bg-gray-700/50 rounded w-48 skeleton-shimmer" />
          <div className="h-64 bg-gray-800/50 rounded-xl skeleton-shimmer" />
        </div>
      </div>
    );
  }

  if (error || !claim) {
    return (
      <div className="min-h-screen bg-gray-950 p-6">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">
              {error instanceof Error ? error.message : 'Claim not found'}
            </p>
          </div>
          <button
            type="button"
            onClick={onLogout}
            className="mt-4 text-sm text-amber-400 hover:text-amber-300"
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
      <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Repair shop</p>
            <h1 className="text-2xl font-bold text-gray-100">RO-{claim.id.slice(0, 8)}</h1>
            <p className="text-sm text-gray-400 mt-1">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model} — VIN: {claim.vin}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge status={claim.status} />
            <button
              type="button"
              onClick={onLogout}
              className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded border border-gray-700"
            >
              Sign out
            </button>
          </div>
        </div>

        <div className="border-b border-gray-700/50">
          <nav className="flex gap-1 flex-wrap">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
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
            <RepairProgressTab
              claimId={claim.id}
              canUpdate={canUpdateProgress}
              onStatusPosted={() => {
                void queryClient.invalidateQueries({ queryKey: qk.repair(claim.id) });
                void queryClient.invalidateQueries({ queryKey: qk.claim(claim.id) });
              }}
            />
          )}
          {activeTab === 'supplement' && (
            <SupplementalTab
              claimId={claim.id}
              canSupplement={canSupplement}
              status={claim.status}
              claimType={claim.claim_type}
              onSuccess={() => {
                void queryClient.invalidateQueries({ queryKey: qk.claim(claim.id) });
              }}
            />
          )}
          {activeTab === 'messages' && (
            <MessagesTab
              followUps={shopMessages}
              claimId={claim.id}
              accentColor="amber"
              senderLabel="From: Insurance Carrier"
              emptyTitle="No messages"
              emptyDescription="No messages addressed to your shop for this repair."
              onRespond={async (messageId, content) => {
                await repairPortalApi.recordFollowUpResponse(claim.id, messageId, content);
                void queryClient.invalidateQueries({ queryKey: qk.claim(claim.id) });
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function VehicleDamageTab({ claim }: { claim: Claim }) {
  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Vehicle</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-xs text-gray-500 uppercase">Vehicle</p>
            <p className="text-gray-300 mt-0.5">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">VIN</p>
            <p className="text-gray-300 font-mono mt-0.5">{claim.vin}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Incident date</p>
            <p className="text-gray-300 mt-0.5">{claim.incident_date ?? '—'}</p>
          </div>
          {claim.estimated_damage != null && (
            <div>
              <p className="text-xs text-gray-500 uppercase">Estimate</p>
              <p className="text-gray-200 font-mono mt-0.5">
                ${Number(claim.estimated_damage).toLocaleString()}
              </p>
            </div>
          )}
        </div>
      </div>
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-amber-500/50">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Damage</h3>
        <p className="text-sm text-gray-400 leading-relaxed">
          {claim.damage_description ?? 'No damage description provided.'}
        </p>
      </div>
    </div>
  );
}

function RepairProgressTab({
  claimId,
  canUpdate,
  onStatusPosted,
}: {
  claimId: string;
  canUpdate: boolean;
  onStatusPosted: () => void;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: qk.repair(claimId),
    queryFn: () => repairPortalApi.getRepairStatus(claimId),
  });
  const [pending, setPending] = useState(false);

  const latest = data?.latest ?? null;
  const history = data?.history ?? [];

  const currentIdx = latest
    ? REPAIR_STATUS_ORDER.indexOf(latest.status as (typeof REPAIR_STATUS_ORDER)[number])
    : -1;

  async function handleStatusChange(status: string) {
    if (!canUpdate || pending) return;
    setPending(true);
    try {
      await repairPortalApi.postRepairStatus(claimId, { status });
      onStatusPosted();
      toast.success('Repair status updated');
    } catch (e) {
      toast.error(getErrorMessage(e, 'Failed to update status'));
    } finally {
      setPending(false);
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
          Stages: received → disassembly → parts ordered → repair → paused (supplement) → paint →
          reassembly → QA → ready.
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
                disabled={!canUpdate || pending}
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
        {latest && (
          <div className="text-xs text-gray-500">
            Current:{' '}
            {latest.status === 'paused_supplement'
              ? 'Repair paused – supplemental pending'
              : String(latest.status).replace(/_/g, ' ')}
            {latest.status_updated_at &&
              ` • ${formatDateTime(String(latest.status_updated_at)) ?? ''}`}
            {latest.notes && ` • ${String(latest.notes)}`}
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
            {[...history].reverse().map((h) => {
              const row = h as Record<string, unknown>;
              return (
                <li key={String(row.id)} className="flex justify-between text-xs text-gray-400">
                  <span>{String(row.status ?? '').replace(/_/g, ' ')}</span>
                  <span>{formatDateTime(String(row.status_updated_at ?? '')) ?? '—'}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function SupplementalTab({
  claimId,
  canSupplement,
  status,
  claimType,
  onSuccess,
}: {
  claimId: string;
  canSupplement: boolean;
  status: string;
  claimType?: string;
  onSuccess: () => void;
}) {
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim()) return;
    setSubmitting(true);
    try {
      const data = await repairPortalApi.postSupplemental(claimId, {
        supplemental_damage_description: description.trim(),
      });
      const amountLabel = data.supplemental_amount != null
        ? `$${data.supplemental_amount.toLocaleString()}`
        : 'TBD';
      toast.success('Supplemental filed', {
        description: `Amount: ${amountLabel}${data.summary ? ` — ${data.summary}` : ''}`,
      });
      setDescription('');
      onSuccess();
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to submit supplemental'));
    } finally {
      setSubmitting(false);
    }
  }

  if (!canSupplement) {
    const reason =
      claimType !== 'partial_loss'
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
      <h3 className="text-sm font-semibold text-gray-300 mb-1">Supplemental damage report</h3>
      <p className="text-xs text-gray-500 mb-4">
        Report additional damage found during teardown or repair that was not on the original
        estimate.
      </p>
      <form onSubmit={handleSubmit} className="space-y-4">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe additional damage..."
          rows={5}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-amber-500/40 resize-none"
          required
        />
        <button
          type="submit"
          disabled={submitting || !description.trim()}
          className="px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-500 disabled:opacity-50 transition-colors"
        >
          {submitting ? 'Submitting...' : 'Submit supplemental'}
        </button>
      </form>
    </div>
  );
}
