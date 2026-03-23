import { useState } from 'react';
import type { Claim } from '../../api/types';

export function ThirdPartyPortalLiabilityPanel({
  claim,
  disputableStatuses,
  onSubmitDispute,
}: {
  claim: Claim;
  disputableStatuses: string[];
  onSubmitDispute: (evidence: string) => Promise<string>;
}) {
  const [evidence, setEvidence] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const canDispute = disputableStatuses.includes(claim.status);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!evidence.trim()) return;
    setSubmitting(true);
    setResult(null);
    try {
      const msg = await onSubmitDispute(evidence.trim());
      setResult(msg);
      setEvidence('');
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
            <p className="text-sm text-gray-300 capitalize mt-0.5">
              {claim.status.replace(/_/g, ' ')}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Claim Type</p>
            <p className="text-sm text-gray-300 capitalize mt-0.5">
              {(claim.claim_type ?? '—').replace(/_/g, ' ')}
            </p>
          </div>
          {claim.liability_percentage != null && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">Liability %</p>
              <p className="text-sm text-gray-300 mt-0.5">{claim.liability_percentage}%</p>
            </div>
          )}
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
            Liability disputes can only be filed when the claim is in an eligible status (
            {disputableStatuses.map((s) => s.replace(/_/g, ' ')).join(', ')}).
            <span className="block mt-1">
              Current status: &quot;{claim.status.replace(/_/g, ' ')}&quot;
            </span>
          </div>
        ) : (
          <>
            {result && (
              <div
                className={`text-sm px-4 py-2 rounded-lg mb-4 ${
                  result.startsWith('Error')
                    ? 'bg-red-500/10 text-red-400'
                    : 'bg-purple-500/10 text-purple-400'
                }`}
              >
                {result}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
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
