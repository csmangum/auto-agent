import { useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getPortalSession } from '../api/portalClient';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import StatusBadge from '../components/StatusBadge';
import EmptyState from '../components/EmptyState';
import MessagesTab from '../components/MessagesTab';
import { formatDateTime } from '../utils/date';
import { usePortal } from '../context/PortalContext';
import { portalApi } from '../api/portalClient';
import type { FollowUpMessage } from '../api/types';

const CUSTOMER_VISIBLE_ACTIONS = new Set([
  'status_change',
  'claim_created',
  'claim_settled',
  'claim_denied',
  'dispute_filed',
  'dispute_resolved',
  'follow_up_sent',
  'follow_up_responded',
  'info_requested',
  'payout_issued',
]);

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

export default function PortalClaimDetail() {
  const { claimId } = useParams<{ claimId: string }>();
  const navigate = useNavigate();
  const { logout } = usePortal();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [activeTab, setActiveTab] = useState<
    'status' | 'documents' | 'messages' | 'repair' | 'payments' | 'rental' | 'dispute'
  >('status');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const { data: claimData, isLoading, error } = useQuery({
    queryKey: ['portal', 'claim', claimId],
    queryFn: () => portalApi.getClaim(claimId!),
    enabled: !!claimId,
  });

  const { data: historyData } = useQuery({
    queryKey: ['portal', 'claim', claimId, 'history'],
    queryFn: () => portalApi.getClaimHistory(claimId!),
    enabled: !!claimId,
  });

  const { data: docsData } = useQuery({
    queryKey: ['portal', 'claim', claimId, 'documents'],
    queryFn: () => portalApi.getDocuments(claimId!),
    enabled: !!claimId && activeTab === 'documents',
  });

  const { data: repairData } = useQuery({
    queryKey: ['portal', 'claim', claimId, 'repair-status'],
    queryFn: () => portalApi.getRepairStatus(claimId!),
    enabled: !!claimId && activeTab === 'repair',
  });

  const { data: paymentsData } = useQuery({
    queryKey: ['portal', 'claim', claimId, 'payments'],
    queryFn: () => portalApi.getPayments(claimId!),
    enabled: !!claimId && (activeTab === 'payments' || activeTab === 'rental'),
  });

  const claim = claimData as Record<string, unknown> | undefined;
  const history = (historyData?.history ?? []) as Array<{
    id?: number;
    action: string;
    new_status?: string;
    details?: string;
    created_at?: string;
  }>;
  const followUps = (claim?.follow_up_messages ?? []) as FollowUpMessage[];
  const customerMessages = followUps.filter(
    (m) => m.user_type === 'claimant' || m.user_type === 'policyholder'
  );
  const customerHistory = history.filter(
    (e) =>
      CUSTOMER_VISIBLE_ACTIONS.has(e.action) || e.action.includes('status')
  );
  const pendingFollowUps = followUps.filter((m) => m.status !== 'responded');
  const   documents = (docsData?.documents ?? []) as Array<{
    id: number;
    document_type?: string;
    received_date?: string;
    url?: string;
    storage_key?: string;
  }>;
  const payments = (paymentsData?.payments ?? []) as Array<{
    id: number;
    amount: number;
    payee: string;
    payee_type: string;
    status: string;
    issued_at?: string;
  }>;
  const rentalPayments = payments.filter(
    (p: { payee_type: string }) => p.payee_type === 'rental_company'
  );

  const invalidateClaim = () => {
    const keys = [
      ['portal', 'claim', claimId],
      ['portal', 'claim', claimId, 'documents'],
    ];
    keys.forEach((k) => queryClient.invalidateQueries({ queryKey: k }));
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !claimId) return;
    setUploading(true);
    setUploadError(null);
    try {
      await portalApi.uploadDocument(claimId, file);
      invalidateClaim();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  if (!claimId) {
    navigate('/portal/claims');
    return null;
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 p-4">
        <div className="h-8 bg-gray-700/50 rounded w-48 animate-pulse" />
        <div className="h-64 bg-gray-800/50 rounded-xl animate-pulse mt-4" />
      </div>
    );
  }

  if (error || !claim) {
    return (
      <div className="min-h-screen bg-gray-950 p-4">
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
          <p className="text-red-400">
            {error instanceof Error ? error.message : 'Claim not found'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/portal/claims')}
          className="mt-4 text-sm text-emerald-400 hover:text-emerald-300"
        >
          Back to My Claims
        </button>
      </div>
    );
  }

  const tabs = [
    { key: 'status' as const, label: 'Status', count: null },
    { key: 'documents' as const, label: 'Documents', count: documents.length },
    {
      key: 'messages' as const,
      label: 'Messages',
      count: pendingFollowUps.length || null,
    },
    { key: 'repair' as const, label: 'Repair Status', count: null },
    { key: 'payments' as const, label: 'Payments', count: null },
    { key: 'rental' as const, label: 'Rental', count: rentalPayments.length },
    { key: 'dispute' as const, label: 'Dispute', count: null },
  ];

  const canDispute = ['settled', 'open'].includes(claim.status as string);

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
        <button
          type="button"
          onClick={() => navigate('/portal/claims')}
          className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-emerald-400 transition-colors mb-3 group"
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
          My Claims
        </button>
        <div className="flex items-center justify-between gap-4 flex-wrap mb-6">
          <div>
            <h2 className="text-2xl font-bold text-gray-100">
              Claim {claimId.slice(0, 8)}...
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}
            </p>
          </div>
          <StatusBadge status={claim.status as string} />
        </div>

        <div className="border-b border-gray-700/50 mb-6 overflow-x-auto">
          <nav className="flex gap-1 min-w-max">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex items-center gap-2 px-3 pb-3 pt-1 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  activeTab === tab.key
                    ? 'border-emerald-500 text-emerald-400'
                    : 'border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-600'
                }`}
              >
                {tab.label}
                {tab.count != null && tab.count > 0 && (
                  <span className="bg-emerald-500/20 text-emerald-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full">
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>

        <div className="animate-fade-in" key={activeTab}>
          {activeTab === 'status' && (
            <StatusTab claim={claim} history={customerHistory} />
          )}
          {activeTab === 'documents' && (
            <DocumentsTab
              claimId={claimId}
              documents={documents}
              uploading={uploading}
              uploadError={uploadError}
              onUploadClick={() => fileInputRef.current?.click()}
              onFileChange={handleFileUpload}
              fileInputRef={fileInputRef}
              onUploadSuccess={invalidateClaim}
            />
          )}
          {activeTab === 'messages' && (
            <MessagesTab
              followUps={customerMessages}
              claimId={claimId}
              accentColor="emerald"
              senderLabel="From: Claims Team"
              emptyTitle="No messages"
              emptyDescription="You don't have any messages from your claims adjuster yet."
              onRespond={async (messageId, content) => {
                await portalApi.recordFollowUpResponse(
                  claimId,
                  messageId,
                  content
                );
                invalidateClaim();
              }}
            />
          )}
          {activeTab === 'repair' && (
            <RepairTab
              claimType={claim.claim_type as string}
              repairData={repairData}
            />
          )}
          {activeTab === 'payments' && <PaymentsTab payments={payments} />}
          {activeTab === 'rental' && (
            <RentalTab rentalPayments={rentalPayments} />
          )}
          {activeTab === 'dispute' && (
            <DisputeTab
              claimId={claimId}
              canDispute={canDispute}
              status={claim.status as string}
              onSuccess={invalidateClaim}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function StatusTab({
  claim,
  history,
}: {
  claim: Record<string, unknown>;
  history: Array<{ action: string; new_status?: string; details?: string; created_at?: string; id?: number }>;
}) {
  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">
          Claim Summary
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field
            label="Vehicle"
            value={`${claim.vehicle_year ?? ''} ${claim.vehicle_make ?? ''} ${claim.vehicle_model ?? ''}`.trim()}
          />
          <Field label="Incident Date" value={(claim.incident_date as string) ?? '—'} />
          <Field label="Filed On" value={formatDateTime(claim.created_at as string) ?? '—'} />
          <Field
            label="Current Status"
            value={(claim.status as string)?.replace(/_/g, ' ') ?? '—'}
            capitalize
          />
          {claim.estimated_damage != null && (
            <Field
              label="Estimated Damage"
              value={`$${Number(claim.estimated_damage).toLocaleString()}`}
              money
            />
          )}
          {claim.payout_amount != null && (
            <Field
              label="Settlement Amount"
              value={`$${Number(claim.payout_amount).toLocaleString()}`}
              payout
            />
          )}
        </div>
      </div>
      {claim.incident_description && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-emerald-500/50">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">
            What Happened
          </h3>
          <p className="text-sm text-gray-400 leading-relaxed">
            {claim.incident_description as string}
          </p>
        </div>
      )}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Timeline</h3>
        {history.length === 0 ? (
          <p className="text-sm text-gray-500">No updates yet.</p>
        ) : (
          <div className="space-y-0">
            {history.map((event, i) => (
              <div key={event.id ?? i} className="flex gap-3 pb-4 last:pb-0">
                <div className="flex flex-col items-center">
                  <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/50 ring-2 ring-emerald-500/20 mt-1" />
                  {i < history.length - 1 && (
                    <div className="w-px flex-1 bg-gray-700/50 mt-1" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-300">
                    {formatAction(event)}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {formatDateTime(event.created_at) ?? ''}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DocumentsTab({
  claimId,
  documents,
  uploading,
  uploadError,
  onUploadClick,
  onFileChange,
  fileInputRef,
}: {
  claimId: string;
  documents: Array<{
    id: number;
    document_type?: string;
    received_date?: string;
    url?: string;
    storage_key?: string;
  }>;
  uploading: boolean;
  uploadError: string | null;
  onUploadClick: () => void;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onUploadSuccess: () => void;
}) {
  return (
    <div className="space-y-4">
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        accept=".pdf,.jpg,.jpeg,.png,.gif,.webp,.heic,.doc,.docx,.xls,.xlsx"
        onChange={onFileChange}
      />
      <div
        onClick={onUploadClick}
        className="border-2 border-dashed border-gray-600 rounded-xl p-6 text-center cursor-pointer hover:border-emerald-500/40 hover:bg-gray-800/30 transition-colors"
      >
        {uploading ? (
          <p className="text-sm text-gray-400">Uploading...</p>
        ) : (
          <p className="text-sm text-gray-400">
            Click to upload documents or photos
          </p>
        )}
      </div>
      {uploadError && (
        <div className="p-3 rounded-lg bg-red-500/10 text-red-400 text-sm">
          {uploadError}
        </div>
      )}
      {documents.length === 0 ? (
        <EmptyState
          icon="📎"
          title="No documents"
          description="No documents uploaded yet."
        />
      ) : (
        <div className="space-y-2">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center justify-between bg-gray-800/50 rounded-lg p-3 border border-gray-700/50"
            >
              <span className="text-sm text-gray-300">
                {doc.document_type ?? 'Document'} — {doc.received_date ?? ''}
              </span>
              {(doc.url || doc.storage_key) && (
                <DocumentDownloadLink
                  claimId={claimId}
                  keyParam={doc.storage_key || doc.url || ''}
                />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RepairTab({
  claimType,
  repairData,
}: {
  claimType: string;
  repairData?: {
    latest: unknown;
    history: unknown[];
    cycle_time_days: number | null;
  };
}) {
  if (claimType !== 'partial_loss') {
    return (
      <EmptyState
        icon="🔧"
        title="Repair status not available"
        description="Repair tracking applies to partial loss claims."
      />
    );
  }
  const history = (repairData?.history ?? []) as Array<{
    status: string;
    status_updated_at?: string;
    notes?: string;
  }>;
  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">
          Repair Progress
        </h3>
        {history.length === 0 ? (
          <p className="text-sm text-gray-500">No repair status updates yet.</p>
        ) : (
          <div className="space-y-0">
            {history.map((h, i) => (
              <div key={i} className="flex gap-3 pb-4 last:pb-0">
                <div className="flex flex-col items-center">
                  <div className="w-2.5 h-2.5 rounded-full bg-amber-500/50 ring-2 ring-amber-500/20 mt-1" />
                  {i < history.length - 1 && (
                    <div className="w-px flex-1 bg-gray-700/50 mt-1" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-300 capitalize">
                    {h.status.replace(/_/g, ' ')}
                  </p>
                  {h.notes && (
                    <p className="text-xs text-gray-500 mt-0.5">{h.notes}</p>
                  )}
                  <p className="text-xs text-gray-500 mt-0.5">
                    {formatDateTime(h.status_updated_at) ?? ''}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PaymentsTab({
  payments,
}: {
  payments: Array<{
    amount: number;
    payee: string;
    payee_type: string;
    status: string;
    issued_at?: string;
  }>;
}) {
  if (payments.length === 0) {
    return (
      <EmptyState
        icon="💳"
        title="No payments"
        description="No payments have been issued for this claim."
      />
    );
  }
  return (
    <div className="space-y-3">
      {payments.map((p) => (
        <div
          key={p.id}
          className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-4"
        >
          <div className="flex justify-between items-start">
            <div>
              <p className="text-sm font-medium text-gray-200">
                ${Number(p.amount).toLocaleString()}
              </p>
              <p className="text-xs text-gray-500">
                {p.payee} — {p.payee_type.replace(/_/g, ' ')}
              </p>
            </div>
            <span className="text-xs text-gray-400 capitalize">
              {p.status.replace(/_/g, ' ')}
            </span>
          </div>
          {p.issued_at && (
            <p className="text-xs text-gray-500 mt-2">
              Issued: {formatDateTime(p.issued_at)}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function RentalTab({
  rentalPayments,
}: {
  rentalPayments: Array<{
    id: number;
    amount: number;
    payee: string;
    status: string;
  }>;
}) {
  return (
    <div className="space-y-6">
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">
          Rental Car Coverage
        </h3>
        <p className="text-sm text-gray-400 mb-4">
          Rental coverage varies by policy. Contact your adjuster to arrange
          rental car reimbursement or direct billing.
        </p>
        {rentalPayments.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs text-gray-500 uppercase tracking-wider">
              Rental Payments
            </p>
            {rentalPayments.map((p) => (
              <div
                key={p.id}
                className="flex justify-between py-2 border-b border-gray-700/50 last:border-0"
              >
                <span className="text-sm text-gray-300">
                  ${Number(p.amount).toLocaleString()}
                </span>
                <span className="text-xs text-gray-500 capitalize">
                  {p.status.replace(/_/g, ' ')}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">
            No rental payments issued yet for this claim.
          </p>
        )}
      </div>
    </div>
  );
}

function DisputeTab({
  claimId,
  canDispute,
  status,
  onSuccess,
}: {
  claimId: string;
  canDispute: boolean;
  status: string;
  onSuccess: () => void;
}) {
  const [form, setForm] = useState({
    dispute_type: 'valuation_disagreement',
    dispute_description: '',
    policyholder_evidence: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.dispute_description.trim()) return;
    setSubmitting(true);
    setResult(null);
    try {
      const data = await portalApi.fileDispute(claimId, {
        dispute_type: form.dispute_type,
        dispute_description: form.dispute_description.trim(),
        policyholder_evidence: form.policyholder_evidence.trim() || undefined,
      });
      setResult(
        `Dispute filed. ${(data as { summary?: string }).summary ?? 'Your adjuster will review.'}`
      );
      setForm({
        dispute_type: 'valuation_disagreement',
        dispute_description: '',
        policyholder_evidence: '',
      });
      onSuccess();
    } catch (err) {
      setResult(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (!canDispute) {
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <EmptyState
          icon="⚖️"
          title="Disputes not available"
          description={`Your claim is currently "${status.replace(/_/g, ' ')}". Disputes can only be filed on settled or resolved claims.`}
        />
      </div>
    );
  }

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-1">File a Dispute</h3>
      <p className="text-xs text-gray-500 mb-4">
        If you disagree with the settlement amount, valuation, or repair
        estimate, you can file a dispute.
      </p>
      {result && (
        <div
          className={`text-sm px-4 py-2 rounded-lg mb-4 ${
            result.startsWith('Error')
              ? 'bg-red-500/10 text-red-400'
              : 'bg-emerald-500/10 text-emerald-400'
          }`}
        >
          {result}
        </div>
      )}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">
            Dispute Type
          </label>
          <select
            value={form.dispute_type}
            onChange={(e) =>
              setForm((f) => ({ ...f, dispute_type: e.target.value }))
            }
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
          >
            <option value="valuation_disagreement">Valuation Disagreement</option>
            <option value="repair_estimate">Repair Estimate Dispute</option>
            <option value="deductible_application">Deductible Application</option>
            <option value="liability_determination">Liability Determination</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Description</label>
          <textarea
            value={form.dispute_description}
            onChange={(e) =>
              setForm((f) => ({ ...f, dispute_description: e.target.value }))
            }
            placeholder="Describe why you disagree with the decision..."
            rows={4}
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-emerald-500/40 resize-none"
            required
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">
            Supporting Evidence (optional)
          </label>
          <textarea
            value={form.policyholder_evidence}
            onChange={(e) =>
              setForm((f) => ({ ...f, policyholder_evidence: e.target.value }))
            }
            placeholder="Reference any supporting documents, photos, or independent appraisals..."
            rows={2}
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-emerald-500/40 resize-none"
          />
        </div>
        <button
          type="submit"
          disabled={submitting || !form.dispute_description.trim()}
          className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-500 disabled:opacity-50 transition-colors"
        >
          {submitting ? 'Filing Dispute...' : 'File Dispute'}
        </button>
      </form>
    </div>
  );
}

function Field({
  label,
  value,
  money,
  payout,
  capitalize,
}: {
  label: string;
  value: string;
  money?: boolean;
  payout?: boolean;
  capitalize?: boolean;
}) {
  return (
    <div>
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p
        className={`text-sm mt-0.5 ${
          payout
            ? 'text-emerald-400 font-semibold font-mono'
            : money
              ? 'text-gray-200 font-mono'
              : capitalize
                ? 'text-gray-300 capitalize'
                : 'text-gray-300'
        }`}
      >
        {value || '—'}
      </p>
    </div>
  );
}

function DocumentDownloadLink({
  claimId,
  keyParam,
}: {
  claimId: string;
  keyParam: string;
}) {
  const [loading, setLoading] = useState(false);
  const handleClick = async () => {
    setLoading(true);
    try {
      const session = getPortalSession();
      const headers: Record<string, string> = {};
      if (session?.token) headers['X-Claim-Access-Token'] = session.token;
      if (session?.policyNumber) headers['X-Policy-Number'] = session.policyNumber;
      if (session?.vin) headers['X-Vin'] = session.vin;
      if (session?.email) headers['X-Email'] = session.email;
      const res = await fetch(
        `/api/portal/claims/${claimId}/attachments/${encodeURIComponent(keyParam)}`,
        { headers }
      );
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = keyParam.split('/').pop() || 'document';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };
  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className="text-sm text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
    >
      {loading ? '...' : 'View'}
    </button>
  );
}

function formatAction(event: {
  action: string;
  new_status?: string;
  details?: string;
}): string {
  const action = event.action.replace(/_/g, ' ');
  if (event.new_status) {
    const statusLabel = event.new_status.replace(/_/g, ' ');
    return `Claim status updated to "${statusLabel}"`;
  }
  if (event.details) {
    try {
      const parsed = JSON.parse(event.details);
      if (parsed.reason) return `${action}: ${parsed.reason}`;
    } catch {
      /* use raw */
    }
  }
  return action.charAt(0).toUpperCase() + action.slice(1);
}
