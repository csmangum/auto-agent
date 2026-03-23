import { useState } from 'react';
import { useNavigate, useParams, Navigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useThirdPartyPortal } from '../context/useThirdPartyPortal';
import { thirdPartyPortalApi } from '../api/thirdPartyPortalClient';
import StatusBadge from '../components/StatusBadge';
import MessagesTab from '../components/MessagesTab';
import { ThirdPartyPortalOverview } from '../components/thirdPartyPortal/ThirdPartyPortalOverview';
import { ThirdPartyPortalLiabilityPanel } from '../components/thirdPartyPortal/ThirdPartyPortalLiabilityPanel';
import { ThirdPartyPortalDocumentUpload } from '../components/thirdPartyPortal/ThirdPartyPortalDocumentUpload';
import type { Claim, AuditEvent, FollowUpMessage } from '../api/types';

/** Must match ``DISPUTABLE_STATUSES`` in ``src/claim_agent/db/constants.py`` (single source of truth). */
const THIRD_PARTY_DISPUTABLE_STATUSES: readonly string[] = ['settled', 'open'];

const qk = {
  claim: (id: string) => ['third-party-portal', 'claim', id] as const,
  history: (id: string) => ['third-party-portal', 'history', id] as const,
};

export default function ThirdPartyPortalClaimDetail() {
  const { claimId: paramClaimId } = useParams<{ claimId: string }>();
  const navigate = useNavigate();
  const { session, logout } = useThirdPartyPortal();
  const claimId = paramClaimId ?? '';

  if (!session?.claimId || !session?.token) {
    return <Navigate to="/third-party-portal/login" replace />;
  }

  if (claimId !== session.claimId) {
    return <Navigate to={`/third-party-portal/claims/${session.claimId}`} replace />;
  }

  return (
    <ThirdPartyPortalClaimBody
      claimId={claimId}
      onLogout={() => {
        logout();
        navigate('/third-party-portal/login', { replace: true });
      }}
    />
  );
}

function ThirdPartyPortalClaimBody({
  claimId,
  onLogout,
}: {
  claimId: string;
  onLogout: () => void;
}) {
  const [activeTab, setActiveTab] = useState<'overview' | 'liability' | 'messages'>('overview');
  const queryClient = useQueryClient();

  const { data: claimRaw, isLoading, error } = useQuery({
    queryKey: qk.claim(claimId),
    queryFn: () => thirdPartyPortalApi.getClaim(claimId),
  });

  const { data: historyData } = useQuery({
    queryKey: qk.history(claimId),
    queryFn: () => thirdPartyPortalApi.getClaimHistory(claimId),
  });

  const claim = claimRaw as Claim | undefined;
  const history = (historyData?.history ?? []) as AuditEvent[];
  const followUps = (claim?.follow_up_messages ?? []) as FollowUpMessage[];

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
        <div className="max-w-4xl mx-auto space-y-4 animate-fade-in">
          <div className="h-8 bg-gray-800/50 rounded w-48 skeleton-shimmer" />
          <div className="h-64 bg-gray-800/50 rounded-xl skeleton-shimmer" />
        </div>
      </div>
    );
  }

  if (error || !claim) {
    return (
      <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-red-400">{error instanceof Error ? error.message : 'Not found'}</p>
          <button
            type="button"
            onClick={onLogout}
            className="mt-4 text-sm text-purple-400 hover:underline"
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  const tabs = [
    { key: 'overview' as const, label: 'Claim Overview' },
    { key: 'liability' as const, label: 'Liability & Subrogation' },
    { key: 'messages' as const, label: `Communications (${followUps.length})` },
  ];

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
      <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs text-gray-500 font-mono">Third-party portal</p>
            <h1 className="text-2xl font-bold text-gray-100">XC-{claim.id.slice(0, 8)}</h1>
            <p className="text-sm text-gray-400 mt-1">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge status={claim.status} />
            <button
              type="button"
              onClick={onLogout}
              className="text-sm text-gray-400 hover:text-purple-400"
            >
              Sign out
            </button>
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
            <div className="space-y-6">
              <ThirdPartyPortalOverview claim={claim} history={history} />
              <ThirdPartyPortalDocumentUpload
                claimId={claimId}
                uploadFn={(id, f) => thirdPartyPortalApi.uploadDocument(id, f)}
                onUploaded={() => {
                  void queryClient.invalidateQueries({ queryKey: qk.claim(claimId) });
                }}
              />
            </div>
          )}
          {activeTab === 'liability' && (
            <ThirdPartyPortalLiabilityPanel
              claim={claim}
              disputableStatuses={[...THIRD_PARTY_DISPUTABLE_STATUSES]}
              onSubmitDispute={async (evidence) => {
                const data = await thirdPartyPortalApi.fileDispute(claim.id, {
                  dispute_type: 'liability_determination',
                  dispute_description: `Third-party liability dispute: ${evidence}`,
                  policyholder_evidence: null,
                });
                return `Dispute filed. Resolution: ${String(data.resolution_type ?? 'pending')} — ${String(data.summary ?? '')}`;
              }}
            />
          )}
          {activeTab === 'messages' && (
            <MessagesTab
              followUps={followUps}
              claimId={claim.id}
              accentColor="purple"
              senderLabel="From: Primary Carrier"
              emptyTitle="No communications"
              emptyDescription="No inter-carrier communications for this claim yet."
              onRespond={async (messageId, text) => {
                await thirdPartyPortalApi.recordFollowUpResponse(claim.id, messageId, text);
                await queryClient.invalidateQueries({ queryKey: qk.claim(claimId) });
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
