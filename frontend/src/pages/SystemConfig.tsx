import { useSystemConfig, useSystemHealth } from '../api/queries';

interface ConfigTableProps {
  title: string;
  config: Record<string, unknown>;
  descriptions?: Record<string, string>;
}

function ConfigTable({ title, config, descriptions = {} }: ConfigTableProps) {
  const entries = Object.entries(config ?? {});
  if (entries.length === 0) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">{title}</h3>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wider text-gray-500">
              <th className="px-4 py-2 font-medium">Parameter</th>
              <th className="px-4 py-2 font-medium">Value</th>
              {Object.keys(descriptions).length > 0 && (
                <th className="px-4 py-2 font-medium">Description</th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {entries.map(([key, value]) => (
              <tr key={key} className="hover:bg-gray-50">
                <td className="px-4 py-2 font-mono text-gray-700 text-xs">{key}</td>
                <td className="px-4 py-2 font-mono text-blue-700 font-medium">
                  {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                </td>
                {Object.keys(descriptions).length > 0 && (
                  <td className="px-4 py-2 text-gray-500 text-xs">
                    {descriptions[key] ?? ''}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const ESCALATION_DESCRIPTIONS: Record<string, string> = {
  confidence_threshold: 'Minimum confidence for automated processing',
  high_value_threshold: 'Payout amount ($) triggering human review',
  similarity_ambiguous_range: 'Similarity score range considered ambiguous [low, high]',
  fraud_damage_vs_value_ratio: 'Damage-to-value ratio triggering fraud check',
  vin_claims_days: 'Days window for checking VIN claim history',
  confidence_decrement_per_pattern: 'Confidence reduction per suspicious pattern',
  description_overlap_threshold: 'Minimum description overlap ratio',
};

const FRAUD_DESCRIPTIONS: Record<string, string> = {
  multiple_claims_days: 'Window (days) for multiple claims check',
  multiple_claims_threshold: 'Number of claims to trigger fraud flag',
  fraud_keyword_score: 'Score points per fraud keyword match',
  multiple_claims_score: 'Score points for multiple claims',
  timing_anomaly_score: 'Score points for timing anomalies',
  damage_mismatch_score: 'Score points for damage/incident mismatch',
  high_risk_threshold: 'Score threshold for high risk',
  medium_risk_threshold: 'Score threshold for medium risk',
  critical_risk_threshold: 'Score threshold for critical risk',
  critical_indicator_count: 'Number of indicators for critical status',
};

interface SystemConfigData {
  escalation?: Record<string, unknown>;
  fraud?: Record<string, unknown>;
  valuation?: Record<string, unknown>;
  partial_loss?: Record<string, unknown>;
  token_budgets?: Record<string, unknown>;
  crew_verbose?: boolean;
}

interface SystemHealthData {
  status: string;
  database: string;
  total_claims: number;
}

export default function SystemConfig() {
  const { data: config, isLoading: configLoading, error: configError } = useSystemConfig();
  const { data: health, isLoading: healthLoading, error: healthError } = useSystemHealth();
  const loading = configLoading || healthLoading;
  const error = configError ?? healthError;

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-gray-900">System Configuration</h1>
        <div className="animate-pulse space-y-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-40 bg-gray-100 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-800">{error instanceof Error ? error.message : 'Unknown error'}</p>
      </div>
    );
  }

  const configData = config as SystemConfigData | undefined;
  const healthData = health as SystemHealthData | undefined;
  if (!configData) return null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">System Configuration</h1>
        <p className="text-sm text-gray-500 mt-1">
          Current configuration thresholds and system health
        </p>
      </div>

      {healthData && (
        <div className={`rounded-xl border p-5 ${
          healthData.status === 'healthy'
            ? 'bg-green-50 border-green-200'
            : 'bg-yellow-50 border-yellow-200'
        }`}>
          <div className="flex items-center gap-3">
            <span className="text-2xl">
              {healthData.status === 'healthy' ? '✅' : '⚠️'}
            </span>
            <div>
              <h3 className="font-semibold text-gray-900">
                System {healthData.status === 'healthy' ? 'Healthy' : 'Degraded'}
              </h3>
              <p className="text-sm text-gray-600">
                Database: {healthData.database} · {healthData.total_claims} claims stored
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-4">
        <ConfigTable
          title="Escalation (Human-in-the-Loop)"
          config={configData.escalation ?? {}}
          descriptions={ESCALATION_DESCRIPTIONS}
        />
        <ConfigTable
          title="Fraud Detection"
          config={configData.fraud ?? {}}
          descriptions={FRAUD_DESCRIPTIONS}
        />
        <ConfigTable
          title="Vehicle Valuation"
          config={configData.valuation ?? {}}
        />
        <ConfigTable
          title="Partial Loss"
          config={configData.partial_loss ?? {}}
        />
        <ConfigTable
          title="Token Budgets"
          config={configData.token_budgets ?? {}}
        />
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">General</h3>
          <p className="text-sm text-gray-600">
            CrewAI Verbose Mode: <span className="font-mono font-medium text-blue-700">
              {configData.crew_verbose ? 'true' : 'false'}
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}
