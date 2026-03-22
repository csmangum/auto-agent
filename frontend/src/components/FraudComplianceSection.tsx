import { Link } from 'react-router-dom';
import { useFraudReportingCompliance } from '../api/queries';
import type { FraudComplianceClaim } from '../api/types';

function formatNicbDueDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

const STATUS_LABELS: Record<string, string> = {
  fraud_suspected: 'Suspected',
  fraud_confirmed: 'Confirmed',
  under_investigation: 'Under Investigation',
};

const STATUS_COLORS: Record<string, string> = {
  fraud_suspected: 'text-yellow-400',
  fraud_confirmed: 'text-red-400',
  under_investigation: 'text-orange-400',
};

function FilingBadge({ filed, label }: { filed: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium ${
        filed
          ? 'bg-green-500/15 text-green-400'
          : 'bg-gray-700/60 text-gray-500'
      }`}
    >
      {filed ? '✓' : '–'} {label}
    </span>
  );
}

function AlertBadge({ alert }: { alert: 'overdue' | 'due_soon' | null }) {
  if (!alert) return null;
  if (alert === 'overdue') {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold bg-red-500/20 text-red-400">
        ⚠ Overdue
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold bg-yellow-500/20 text-yellow-400">
      ⏰ Due Soon
    </span>
  );
}

function SummaryBar({ claims }: { claims: FraudComplianceClaim[] }) {
  const total = claims.length;
  const compliant = claims.filter((c) => c.compliant).length;
  const pending = total - compliant;
  const overdue = claims.filter((c) => c.nicb_overdue).length;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
      <div className="bg-gray-700/40 rounded-lg p-3 text-center">
        <div className="text-2xl font-bold text-gray-100">{total}</div>
        <div className="text-xs text-gray-400 mt-0.5">Total Flagged</div>
      </div>
      <div className="bg-green-500/10 rounded-lg p-3 text-center border border-green-500/20">
        <div className="text-2xl font-bold text-green-400">{compliant}</div>
        <div className="text-xs text-gray-400 mt-0.5">Filings Complete</div>
      </div>
      <div className="bg-yellow-500/10 rounded-lg p-3 text-center border border-yellow-500/20">
        <div className="text-2xl font-bold text-yellow-400">{pending}</div>
        <div className="text-xs text-gray-400 mt-0.5">Pending Filings</div>
      </div>
      <div className="bg-red-500/10 rounded-lg p-3 text-center border border-red-500/20">
        <div className="text-2xl font-bold text-red-400">{overdue}</div>
        <div className="text-xs text-gray-400 mt-0.5">NICB Overdue</div>
      </div>
    </div>
  );
}

export default function FraudComplianceSection() {
  const { data, isLoading, error } = useFraudReportingCompliance({ limit: 20 });

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
          🛡️ Fraud Compliance
        </h3>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-10 bg-gray-700/40 rounded skeleton-shimmer" />
          ))}
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
          <span>⚠️</span>
          <span>Failed to load fraud compliance data.</span>
        </div>
      )}

      {!isLoading && !error && data && (
        <>
          <SummaryBar claims={data.claims} />

          {data.claims.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-4">No fraud-flagged claims found.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-gray-500 border-b border-gray-700/50">
                    <th className="pb-2 pr-3 font-medium">Claim</th>
                    <th className="pb-2 pr-3 font-medium">Status</th>
                    <th className="pb-2 pr-3 font-medium">State</th>
                    <th className="pb-2 pr-3 font-medium">Filings</th>
                    <th className="pb-2 font-medium">NICB</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/30">
                  {data.claims.map((claim) => {
                    const nicbDueLabel = formatNicbDueDate(claim.nicb_due_at);
                    return (
                      <tr key={claim.claim_id} className="hover:bg-gray-700/20 transition-colors">
                        <td className="py-2 pr-3">
                          <Link
                            to={`/claims/${claim.claim_id}`}
                            className="text-blue-400 hover:text-blue-300 font-mono transition-colors"
                          >
                            {claim.claim_id}
                          </Link>
                        </td>
                        <td className="py-2 pr-3">
                          <span className={`font-medium ${STATUS_COLORS[claim.status] ?? 'text-gray-400'}`}>
                            {STATUS_LABELS[claim.status] ?? claim.status}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-gray-400">
                          {claim.loss_state ?? '—'}
                        </td>
                        <td className="py-2 pr-3">
                          <div className="flex flex-wrap gap-1">
                            {claim.required_filing_types.includes('state_bureau') && (
                              <FilingBadge filed={claim.state_report_filed} label="State" />
                            )}
                            {claim.required_filing_types.includes('nicb') && (
                              <FilingBadge filed={claim.nicb_filed} label="NICB" />
                            )}
                            {claim.required_filing_types.includes('niss') && (
                              <FilingBadge filed={claim.niss_filed} label="NISS" />
                            )}
                            {claim.required_filing_types.length === 0 && (
                              <span className="text-gray-600">None required</span>
                            )}
                          </div>
                        </td>
                        <td className="py-2">
                          <div className="flex flex-col gap-0.5">
                            <AlertBadge alert={claim.nicb_alert} />
                            {!claim.nicb_alert && claim.nicb_filed && (
                              <span className="text-xs text-green-400">Filed</span>
                            )}
                            {!claim.nicb_alert && !claim.nicb_filed && !claim.nicb_required && (
                              <span className="text-xs text-gray-600">N/A</span>
                            )}
                            {!claim.nicb_alert && claim.nicb_required && !claim.nicb_filed && (
                              <span className="text-xs text-gray-400">
                                Pending
                                {nicbDueLabel && (
                                  <span className="text-gray-500"> · due {nicbDueLabel}</span>
                                )}
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
