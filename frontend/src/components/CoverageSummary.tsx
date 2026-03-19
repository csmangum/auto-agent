import { usePolicies } from '../api/queries';
import EmptyState from './EmptyState';

interface CoverageSummaryProps {
  policyNumber: string;
  vin: string;
  claimType?: string;
}

const COVERAGE_RELEVANCE: Record<string, string[]> = {
  partial_loss: ['collision', 'comprehensive'],
  total_loss: ['collision', 'comprehensive', 'gap'],
  bodily_injury: ['liability_bi', 'um_uim'],
  fraud: ['collision', 'comprehensive'],
  new: ['collision', 'comprehensive', 'liability'],
  supplemental: ['collision'],
  subrogation: ['collision', 'comprehensive'],
};

export default function CoverageSummary({ policyNumber, vin, claimType }: CoverageSummaryProps) {
  const { data, isLoading, error } = usePolicies();

  if (isLoading) {
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-6 bg-gray-700/30 rounded skeleton-shimmer" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
          <p className="text-sm text-red-400">
            {error instanceof Error ? error.message : 'Failed to load policy data'}
          </p>
        </div>
      </div>
    );
  }

  const policies = data?.policies ?? [];
  const policy = policies.find((p) => p.policy_number === policyNumber);

  if (!policy) {
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <EmptyState
          icon="🛡️"
          title="Policy not found"
          description={`No policy data found for ${policyNumber}. Policy may not be loaded in the system.`}
        />
      </div>
    );
  }

  const relevantCoverages = claimType ? (COVERAGE_RELEVANCE[claimType] ?? []) : [];

  return (
    <div className="space-y-6">
      {/* Policy overview */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Policy Details</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Policy Number</p>
            <p className="text-sm font-mono text-gray-200 mt-0.5">{policy.policy_number}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Status</p>
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ring-1 ring-inset mt-0.5 ${
              policy.status === 'active'
                ? 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/20'
                : 'bg-gray-500/15 text-gray-400 ring-gray-500/20'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                policy.status === 'active' ? 'bg-emerald-400' : 'bg-gray-400'
              }`} />
              {policy.status}
            </span>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">Vehicles on Policy</p>
            <p className="text-sm text-gray-200 mt-0.5">{policy.vehicle_count ?? policy.vehicles?.length ?? 0}</p>
          </div>
        </div>
      </div>

      {/* Coverage limits */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Coverage Limits</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {policy.liability_limits?.bi_per_accident != null && (
            <div className={`p-3 rounded-lg ${
              relevantCoverages.includes('liability_bi') || relevantCoverages.includes('liability')
                ? 'bg-blue-500/10 ring-1 ring-blue-500/20'
                : 'bg-gray-900/50'
            }`}>
              <p className="text-xs text-gray-500">Bodily Injury (per accident)</p>
              <p className="text-lg font-bold text-gray-100 mt-1">
                ${policy.liability_limits.bi_per_accident.toLocaleString()}
              </p>
              {relevantCoverages.includes('liability_bi') && (
                <p className="text-xs text-blue-400 mt-1">✓ Relevant to this claim</p>
              )}
            </div>
          )}
          {policy.liability_limits?.pd_per_accident != null && (
            <div className={`p-3 rounded-lg ${
              relevantCoverages.includes('liability') ? 'bg-blue-500/10 ring-1 ring-blue-500/20' : 'bg-gray-900/50'
            }`}>
              <p className="text-xs text-gray-500">Property Damage (per accident)</p>
              <p className="text-lg font-bold text-gray-100 mt-1">
                ${policy.liability_limits.pd_per_accident.toLocaleString()}
              </p>
            </div>
          )}
          {policy.collision_deductible != null && (
            <div className={`p-3 rounded-lg ${
              relevantCoverages.includes('collision') ? 'bg-blue-500/10 ring-1 ring-blue-500/20' : 'bg-gray-900/50'
            }`}>
              <p className="text-xs text-gray-500">Collision Deductible</p>
              <p className="text-lg font-bold text-gray-100 mt-1">
                ${policy.collision_deductible.toLocaleString()}
              </p>
              {relevantCoverages.includes('collision') && (
                <p className="text-xs text-blue-400 mt-1">✓ Relevant to this claim</p>
              )}
            </div>
          )}
          {policy.comprehensive_deductible != null && (
            <div className={`p-3 rounded-lg ${
              relevantCoverages.includes('comprehensive') ? 'bg-blue-500/10 ring-1 ring-blue-500/20' : 'bg-gray-900/50'
            }`}>
              <p className="text-xs text-gray-500">Comprehensive Deductible</p>
              <p className="text-lg font-bold text-gray-100 mt-1">
                ${policy.comprehensive_deductible.toLocaleString()}
              </p>
              {relevantCoverages.includes('comprehensive') && (
                <p className="text-xs text-blue-400 mt-1">✓ Relevant to this claim</p>
              )}
            </div>
          )}
        </div>
        {!policy.liability_limits && !policy.collision_deductible && !policy.comprehensive_deductible && (
          <p className="text-sm text-gray-500">No coverage details available for this policy.</p>
        )}
      </div>

      {/* Vehicles */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Vehicles on Policy</h3>
        {(!policy.vehicles || policy.vehicles.length === 0) ? (
          <p className="text-sm text-gray-500">No vehicle details available.</p>
        ) : (
          <div className="space-y-3">
            {policy.vehicles.map((v) => {
              const isMatch = v.vin === vin;
              return (
                <div
                  key={v.vin}
                  className={`rounded-lg p-3 ring-1 ${
                    isMatch
                      ? 'ring-blue-500/50 bg-blue-500/10'
                      : 'ring-gray-700/50 bg-gray-900/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-gray-200">
                        {v.vehicle_year} {v.vehicle_make} {v.vehicle_model}
                      </p>
                      <p className="text-xs font-mono text-gray-500 mt-0.5">VIN: {v.vin}</p>
                    </div>
                    {isMatch && (
                      <span className="text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded ring-1 ring-blue-500/30">
                        ✓ Claim Vehicle
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
