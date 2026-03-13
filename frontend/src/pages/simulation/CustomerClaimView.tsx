import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import StatusBadge from '../../components/StatusBadge';
import EmptyState from '../../components/EmptyState';
import MessagesTab from '../../components/MessagesTab';
import { formatDateTime } from '../../utils/date';
import { queryKeys } from '../../api/queries';
import { postClaimDispute } from '../../api/client';
import type { Claim, AuditEvent, FollowUpMessage } from '../../api/types';

interface Props {
  claim: Claim;
  history: AuditEvent[];
  onBack: () => void;
}

const CUSTOMER_VISIBLE_ACTIONS = new Set([
  'status_change', 'claim_created', 'claim_settled', 'claim_denied',
  'dispute_filed', 'dispute_resolved', 'follow_up_sent', 'follow_up_responded',
  'info_requested', 'payout_issued',
]);

export default function CustomerClaimView({ claim, history, onBack }: Props) {
  const [activeTab, setActiveTab] = useState<'status' | 'messages' | 'dispute'>('status');
  const followUps = claim.follow_up_messages ?? [];
  const pendingFollowUps = followUps.filter((m) => m.status !== 'responded');

  const customerHistory = history.filter(
    (e) => CUSTOMER_VISIBLE_ACTIONS.has(e.action) || e.action.includes('status')
  );

  const customerMessages = followUps.filter(
    (m) => m.user_type === 'claimant' || m.user_type === 'policyholder'
  );

  const tabs = [
    { key: 'status' as const, label: 'Claim Status', count: null },
    { key: 'messages' as const, label: 'Messages', count: pendingFollowUps.length || null },
    { key: 'dispute' as const, label: 'Dispute', count: null },
  ];

  const canDispute = ['settled', 'open'].includes(claim.status);

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-emerald-400 transition-colors mb-3 group"
        >
          <svg className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          My Claims
        </button>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-gray-100">
              Claim {claim.id.slice(0, 8)}...
            </h1>
            <p className="text-sm text-gray-400 mt-1">
              {claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}
            </p>
          </div>
          <StatusBadge status={claim.status} />
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-700/50">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 pb-3 pt-1 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-emerald-500 text-emerald-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-600'
              }`}
            >
              {tab.label}
              {tab.count != null && (
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
          <ClaimStatusTab claim={claim} history={customerHistory} />
        )}
        {activeTab === 'messages' && (
          <MessagesTab
            followUps={customerMessages}
            claimId={claim.id}
            accentColor="emerald"
            senderLabel="From: Claims Team"
            emptyTitle="No messages"
            emptyDescription="You don't have any messages from your claims adjuster yet."
          />
        )}
        {activeTab === 'dispute' && (
          <DisputeTab claimId={claim.id} canDispute={canDispute} status={claim.status} />
        )}
      </div>
    </div>
  );
}

function ClaimStatusTab({ claim, history }: { claim: Claim; history: AuditEvent[] }) {
  return (
    <div className="space-y-6">
      {/* Claim summary card */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Claim Summary</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Vehicle" value={`${claim.vehicle_year ?? ''} ${claim.vehicle_make ?? ''} ${claim.vehicle_model ?? ''}`.trim()} />
          <Field label="Incident Date" value={claim.incident_date ?? '—'} />
          <Field label="Filed On" value={formatDateTime(claim.created_at) ?? '—'} />
          <Field label="Current Status" value={claim.status.replace(/_/g, ' ')} capitalize />
          {claim.estimated_damage != null && (
            <Field label="Estimated Damage" value={`$${Number(claim.estimated_damage).toLocaleString()}`} money />
          )}
          {claim.payout_amount != null && (
            <Field label="Settlement Amount" value={`$${Number(claim.payout_amount).toLocaleString()}`} payout />
          )}
        </div>
      </div>

      {/* Incident details */}
      {claim.incident_description && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-emerald-500/50">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">What Happened</h3>
          <p className="text-sm text-gray-400 leading-relaxed">{claim.incident_description}</p>
        </div>
      )}

      {/* Timeline */}
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
                  {i < history.length - 1 && <div className="w-px flex-1 bg-gray-700/50 mt-1" />}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-300">{formatAction(event)}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{formatDateTime(event.created_at) ?? ''}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DisputeTab({ claimId, canDispute, status }: { claimId: string; canDispute: boolean; status: string }) {
  const [form, setForm] = useState({
    dispute_type: 'valuation_disagreement',
    dispute_description: '',
    policyholder_evidence: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const queryClient = useQueryClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.dispute_description.trim()) return;
    setSubmitting(true);
    setResult(null);
    try {
      const data = await postClaimDispute(claimId, {
        dispute_type: form.dispute_type,
        dispute_description: form.dispute_description.trim(),
        policyholder_evidence: form.policyholder_evidence.trim() || null,
      });
      setResult(`Dispute filed successfully. Resolution: ${data.resolution_type ?? 'pending'} — ${data.summary ?? ''}`);
      setForm({ dispute_type: 'valuation_disagreement', dispute_description: '', policyholder_evidence: '' });
      
      await queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.claimHistory(claimId) });
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
        If you disagree with the settlement amount, valuation, or repair estimate, you can file a dispute.
      </p>

      {result && (
        <div className={`text-sm px-4 py-2 rounded-lg mb-4 ${
          result.startsWith('Error') ? 'bg-red-500/10 text-red-400' : 'bg-emerald-500/10 text-emerald-400'
        }`}>
          {result}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Dispute Type</label>
          <select
            value={form.dispute_type}
            onChange={(e) => setForm((f) => ({ ...f, dispute_type: e.target.value }))}
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
            onChange={(e) => setForm((f) => ({ ...f, dispute_description: e.target.value }))}
            placeholder="Describe why you disagree with the decision..."
            rows={4}
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-emerald-500/40 resize-none"
            required
          />
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Supporting Evidence (optional)</label>
          <textarea
            value={form.policyholder_evidence}
            onChange={(e) => setForm((f) => ({ ...f, policyholder_evidence: e.target.value }))}
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

function Field({ label, value, money, payout, capitalize }: {
  label: string;
  value: string;
  money?: boolean;
  payout?: boolean;
  capitalize?: boolean;
}) {
  return (
    <div>
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-sm mt-0.5 ${
        payout ? 'text-emerald-400 font-semibold font-mono'
          : money ? 'text-gray-200 font-mono'
          : capitalize ? 'text-gray-300 capitalize'
          : 'text-gray-300'
      }`}>
        {value || '—'}
      </p>
    </div>
  );
}

function formatAction(event: AuditEvent): string {
  const action = event.action.replace(/_/g, ' ');
  if (event.new_status) {
    const statusLabel = event.new_status.replace(/_/g, ' ');
    return `Claim status updated to "${statusLabel}"`;
  }
  if (event.details) {
    try {
      const parsed = JSON.parse(event.details);
      if (parsed.reason) return `${action}: ${parsed.reason}`;
    } catch { /* use raw */ }
  }
  return action.charAt(0).toUpperCase() + action.slice(1);
}
