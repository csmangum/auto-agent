import { useState } from 'react';
import { useParams } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import TypeBadge from '../components/TypeBadge';
import AuditTimeline from '../components/AuditTimeline';
import EmptyState from '../components/EmptyState';
import StructuredOutputDisplay from '../components/StructuredOutputDisplay';
import { useClaim, useClaimHistory, useClaimWorkflows } from '../api/queries';
import { formatDateTime } from '../utils/date';

export default function ClaimDetail() {
  const { claimId } = useParams<{ claimId: string }>();
  const [activeTab, setActiveTab] = useState('overview');
  const { data: claim, isLoading: claimLoading, error: claimError } = useClaim(claimId);
  const {
    data: historyData,
    isLoading: historyLoading,
    error: historyError,
  } = useClaimHistory(claimId);
  const {
    data: workflowsData,
    isLoading: workflowsLoading,
    error: workflowsError,
  } = useClaimWorkflows(claimId);
  const history = historyData?.history ?? [];
  const workflows = workflowsData?.workflows ?? [];
  const notes = claim?.notes ?? [];
  const followUps = claim?.follow_up_messages ?? [];
  const attachments = claim?.attachments ?? [];
  const notesFollowUpsCount = notes.length + followUps.length;
  const loading = claimLoading || historyLoading || workflowsLoading;
  const error = claimError ?? historyError ?? workflowsError;

  if (loading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="h-8 bg-gray-700/50 rounded w-48 skeleton-shimmer" />
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 space-y-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-6 bg-gray-700/30 rounded w-full skeleton-shimmer" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 animate-fade-in">
        <PageHeader title="Claim" backTo="/claims" backLabel="Claims" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (!claim) return null;

  const tabs = [
    { key: 'overview', label: 'Overview', icon: '📋' },
    { key: 'documents', label: `Documents (${attachments.length})`, icon: '📎' },
    { key: 'notes', label: `Notes & Follow-ups (${notesFollowUpsCount})`, icon: '💬' },
    { key: 'audit', label: `Audit Log (${history.length})`, icon: '📜' },
    { key: 'workflows', label: `Workflows (${workflows.length})`, icon: '🔄' },
  ];

  const fields = [
    { label: 'Policy Number', value: claim.policy_number },
    { label: 'VIN', value: claim.vin },
    { label: 'Vehicle', value: `${claim.vehicle_year ?? ''} ${claim.vehicle_make ?? ''} ${claim.vehicle_model ?? ''}`.trim() || '—' },
    { label: 'Incident Date', value: claim.incident_date },
    { label: 'Estimated Damage', value: claim.estimated_damage != null ? `$${Number(claim.estimated_damage).toLocaleString()}` : '—', isMoney: true },
    { label: 'Payout Amount', value: claim.payout_amount != null ? `$${Number(claim.payout_amount).toLocaleString()}` : '—', isMoney: true, isPayout: claim.payout_amount != null },
    { label: 'Created', value: formatDateTime(claim.created_at) ?? '—' },
    { label: 'Updated', value: formatDateTime(claim.updated_at) ?? '—' },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <PageHeader
        title={claim.id}
        backTo="/claims"
        backLabel="Claims"
        actions={
          <div className="flex items-center gap-3">
            <TypeBadge type={claim.claim_type} />
            <StatusBadge status={claim.status} />
          </div>
        }
      />

      {/* Tabs */}
      <div className="border-b border-gray-700/50">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 pb-3 pt-1 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-600'
              }`}
            >
              <span className="text-sm">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div className="animate-fade-in" key={activeTab}>
        {activeTab === 'overview' && (
          <div className="space-y-6">
            {/* Details grid */}
            <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Claim Details</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {fields.map((f) => (
                  <div key={f.label}>
                    <p className="text-xs text-gray-500 uppercase tracking-wider">{f.label}</p>
                    <p className={`text-sm mt-0.5 font-mono ${
                      f.isPayout ? 'text-emerald-400 font-semibold' : f.isMoney ? 'text-gray-200' : 'text-gray-300'
                    }`}>
                      {f.value ?? '—'}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Descriptions */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-blue-500/50">
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Incident Description</h3>
                <p className="text-sm text-gray-400 leading-relaxed">
                  {claim.incident_description ?? 'No description provided.'}
                </p>
              </div>
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-amber-500/50">
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Damage Description</h3>
                <p className="text-sm text-gray-400 leading-relaxed">
                  {claim.damage_description ?? 'No description provided.'}
                </p>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'documents' && (
          <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Documents & Attachments</h3>
            <p className="text-xs text-gray-500 mb-4">
              Photos, invoices, receipts, estimates, and other supporting documents for this claim.
            </p>
            {attachments.length === 0 ? (
              <EmptyState
                icon="📎"
                title="No documents"
                description="No attachments, invoices, or receipts have been uploaded for this claim."
              />
            ) : (
              <div className="space-y-3">
                {attachments.map((att, i) => {
                  const typeLabel =
                    att.type === 'photo'
                      ? 'Photo'
                      : att.type === 'pdf'
                        ? 'PDF'
                        : att.type === 'estimate'
                          ? 'Estimate'
                          : 'Document';
                  const icon =
                    att.type === 'photo'
                      ? '🖼️'
                      : att.type === 'pdf'
                        ? '📄'
                        : att.type === 'estimate'
                          ? '📋'
                          : '📎';
                  const filename = att.url.split('/').pop() ?? `Document ${i + 1}`;
                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between gap-4 rounded-lg bg-gray-900/50 p-3 ring-1 ring-gray-700/50 hover:ring-gray-600/50 transition-colors"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <span className="text-lg shrink-0">{icon}</span>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-200 truncate">
                            {att.description ?? filename}
                          </p>
                          <p className="text-xs text-gray-500">{typeLabel}</p>
                        </div>
                      </div>
                      <a
                        href={att.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="shrink-0 text-sm font-medium text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        View →
                      </a>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {activeTab === 'notes' && (
          <div className="space-y-6">
            {/* Claim notes */}
            <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Claim Notes</h3>
              {notes.length === 0 ? (
                <EmptyState
                  icon="📝"
                  title="No notes"
                  description="No claim notes recorded yet."
                />
              ) : (
                <div className="space-y-3">
                  {notes.map((n, i) => (
                    <div
                      key={n.id ?? i}
                      className="rounded-lg bg-gray-900/50 p-3 ring-1 ring-gray-700/50"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-medium text-blue-400">{n.actor_id}</span>
                        {n.created_at && (
                          <span className="text-xs text-gray-500">
                            {formatDateTime(n.created_at)}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-300 whitespace-pre-wrap">{n.note}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Follow-up messages */}
            <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Follow-up Messages</h3>
              {followUps.length === 0 ? (
                <EmptyState
                  icon="✉️"
                  title="No follow-ups"
                  description="No follow-up messages sent for this claim."
                />
              ) : (
                <div className="space-y-4">
                  {followUps.map((msg) => (
                    <div
                      key={msg.id}
                      className="rounded-lg bg-gray-900/50 p-4 ring-1 ring-gray-700/50"
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs font-medium text-amber-400 capitalize">
                          {msg.user_type.replaceAll('_', ' ')}
                        </span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded ${
                            msg.status === 'responded'
                              ? 'bg-emerald-500/20 text-emerald-400'
                              : msg.status === 'sent'
                                ? 'bg-blue-500/20 text-blue-400'
                                : 'bg-gray-500/20 text-gray-400'
                          }`}
                        >
                          {msg.status}
                        </span>
                        {msg.created_at && (
                          <span className="text-xs text-gray-500">
                            {formatDateTime(msg.created_at)}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-300 mb-2">{msg.message_content}</p>
                      {msg.response_content && (
                        <div className="mt-2 pt-2 border-t border-gray-700/50">
                          <p className="text-xs text-gray-500 mb-1">Response</p>
                          <p className="text-sm text-gray-300 whitespace-pre-wrap">
                            {msg.response_content}
                          </p>
                          {msg.responded_at && (
                            <p className="text-xs text-gray-500 mt-1">
                              {formatDateTime(msg.responded_at)}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'audit' && (
          <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Audit History</h3>
            <AuditTimeline events={history} />
          </div>
        )}

        {activeTab === 'workflows' && (
          <div className="space-y-4">
            {workflows.length === 0 ? (
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
                <EmptyState
                  icon="🔄"
                  title="No workflow runs"
                  description="No workflow runs recorded for this claim."
                />
              </div>
            ) : (
              workflows.map((wf, i) => (
                <div key={wf.id ?? i} className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <h3 className="text-sm font-semibold text-gray-300">
                      Run #{wf.id}
                    </h3>
                    <TypeBadge type={wf.claim_type} />
                    <span className="text-xs text-gray-500">
                      {formatDateTime(wf.created_at) ?? ''}
                    </span>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Router Output</p>
                      <div className="bg-gray-900 rounded-lg p-3 ring-1 ring-gray-700/50">
                        <StructuredOutputDisplay value={wf.router_output ?? ''} />
                      </div>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Workflow Output</p>
                      <div className="bg-gray-900 rounded-lg p-3 max-h-96 overflow-y-auto ring-1 ring-gray-700/50">
                        <StructuredOutputDisplay value={wf.workflow_output ?? ''} />
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
