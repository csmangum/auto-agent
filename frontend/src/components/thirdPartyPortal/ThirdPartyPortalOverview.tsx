import type { Claim, AuditEvent } from '../../api/types';
import { formatDateTime } from '../../utils/date';

export function ThirdPartyPortalOverview({
  claim,
  history,
  demandLabel = 'Demand Amount',
}: {
  claim: Claim;
  history: AuditEvent[];
  demandLabel?: string;
}) {
  const relevantHistory = history.filter(
    (e) =>
      e.action.includes('status') ||
      e.action.includes('settled') ||
      e.action.includes('subrogation')
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
            <p className="text-sm text-gray-300 mt-0.5 capitalize">
              {claim.status.replace(/_/g, ' ')}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Type</p>
            <p className="text-sm text-gray-300 mt-0.5 capitalize">
              {(claim.claim_type ?? '—').replace(/_/g, ' ')}
            </p>
          </div>
          {claim.payout_amount != null && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">{demandLabel}</p>
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
                  {i < relevantHistory.length - 1 && (
                    <div className="w-px flex-1 bg-gray-700/50 mt-1" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-300">
                    {event.new_status
                      ? `Status: ${event.new_status.replace(/_/g, ' ')}`
                      : event.action.replace(/_/g, ' ')}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {formatDateTime(event.created_at) ?? ''}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
