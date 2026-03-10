import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import StatusBadge from '../components/StatusBadge';
import AuditTimeline from '../components/AuditTimeline';
import { useClaim, useClaimHistory, useClaimWorkflows } from '../api/queries';
import { formatDateTime } from '../utils/date';

export default function ClaimDetail() {
  const { claimId } = useParams<{ claimId: string }>();
  const [activeTab, setActiveTab] = useState('overview');
  const { data: claim, isLoading: claimLoading, error: claimError } = useClaim(claimId);
  const { data: historyData } = useClaimHistory(claimId);
  const { data: workflowsData } = useClaimWorkflows(claimId);
  const history = historyData?.history ?? [];
  const workflows = workflowsData?.workflows ?? [];
  const loading = claimLoading;
  const error = claimError;

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 bg-gray-200 rounded w-48 animate-pulse" />
        <div className="bg-white rounded-xl border p-6 animate-pulse space-y-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-6 bg-gray-100 rounded w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Link to="/claims" className="text-blue-600 hover:text-blue-800 text-sm">&larr; Back to Claims</Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (!claim) return null;

  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'audit', label: `Audit Log (${history.length})` },
    { key: 'workflows', label: `Workflow Runs (${workflows.length})` },
  ];

  const fields = [
    { label: 'Claim ID', value: claim.id },
    { label: 'Policy Number', value: claim.policy_number },
    { label: 'VIN', value: claim.vin },
    { label: 'Vehicle', value: `${claim.vehicle_year ?? ''} ${claim.vehicle_make ?? ''} ${claim.vehicle_model ?? ''}`.trim() || '—' },
    { label: 'Incident Date', value: claim.incident_date },
    { label: 'Claim Type', value: claim.claim_type?.replace(/_/g, ' ') ?? 'unclassified' },
    { label: 'Estimated Damage', value: claim.estimated_damage != null ? `$${Number(claim.estimated_damage).toLocaleString()}` : '—' },
    { label: 'Payout Amount', value: claim.payout_amount != null ? `$${Number(claim.payout_amount).toLocaleString()}` : '—' },
    { label: 'Created', value: formatDateTime(claim.created_at) ?? '—' },
    { label: 'Updated', value: formatDateTime(claim.updated_at) ?? '—' },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4 flex-wrap">
        <Link to="/claims" className="text-blue-600 hover:text-blue-800 text-sm">&larr; Claims</Link>
        <h1 className="text-2xl font-bold text-gray-900 font-mono">{claim.id}</h1>
        <StatusBadge status={claim.status} />
      </div>

      <div className="border-b border-gray-200">
        <nav className="flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-sm font-semibold text-gray-700 mb-4">Claim Details</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {fields.map((f) => (
                <div key={f.label}>
                  <p className="text-xs text-gray-500 uppercase tracking-wider">{f.label}</p>
                  <p className="text-sm text-gray-900 mt-0.5 font-mono">{f.value ?? '—'}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Incident Description</h3>
              <p className="text-sm text-gray-600 leading-relaxed">
                {claim.incident_description ?? 'No description provided.'}
              </p>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Damage Description</h3>
              <p className="text-sm text-gray-600 leading-relaxed">
                {claim.damage_description ?? 'No description provided.'}
              </p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'audit' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Audit History</h3>
          <AuditTimeline events={history} />
        </div>
      )}

      {activeTab === 'workflows' && (
        <div className="space-y-4">
          {workflows.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <p className="text-gray-500 text-sm">No workflow runs recorded for this claim.</p>
            </div>
          ) : (
            workflows.map((wf, i) => (
              <div key={wf.id ?? i} className="bg-white rounded-xl border border-gray-200 p-6">
                <div className="flex items-center gap-3 mb-4">
                  <h3 className="text-sm font-semibold text-gray-700">
                    Run #{wf.id} — {wf.claim_type ?? 'unknown'}
                  </h3>
                  <span className="text-xs text-gray-400">
                    {formatDateTime(wf.created_at) ?? ''}
                  </span>
                </div>

                <div className="space-y-4">
                  <div>
                    <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Router Output</p>
                    <pre className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 whitespace-pre-wrap font-mono overflow-x-auto">
                      {wf.router_output ?? '—'}
                    </pre>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Workflow Output</p>
                    <pre className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 whitespace-pre-wrap font-mono overflow-x-auto max-h-96 overflow-y-auto">
                      {wf.workflow_output ?? '—'}
                    </pre>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
