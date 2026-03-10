import PageHeader from '../components/PageHeader';
import { useSystemConfig, useSystemHealth } from '../api/queries';

interface ConfigTableProps {
  title: string;
  icon?: string;
  config: Record<string, unknown>;
  descriptions?: Record<string, string>;
}

function ConfigTable({ title, icon, config, descriptions = {} }: ConfigTableProps) {
  const entries = Object.entries(config ?? {});
  if (entries.length === 0) return null;

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
      <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
        {icon && <span>{icon}</span>}
        {title}
      </h3>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-700/50 text-left text-xs uppercase tracking-wider text-gray-500">
              <th className="px-4 py-2 font-medium">Parameter</th>
              <th className="px-4 py-2 font-medium">Value</th>
              {Object.keys(descriptions).length > 0 && (
                <th className="px-4 py-2 font-medium">Description</th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700/30">
            {entries.map(([key, value]) => (
              <tr key={key} className="hover:bg-gray-800/80 transition-colors">
                <td className="px-4 py-2.5 font-mono text-gray-400 text-xs">{key}</td>
                <td className="px-4 py-2.5 font-mono text-blue-400 font-medium text-xs">
                  {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                </td>
                {Object.keys(descriptions).length > 0 && (
                  <td className="px-4 py-2.5 text-gray-500 text-xs">
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

export default function SystemConfig() {
  const { data: config, isLoading: configLoading, error: configError } = useSystemConfig();
  const { data: health, isLoading: healthLoading, error: healthError } = useSystemHealth();
  const loading = configLoading || healthLoading;
  const error = configError ?? healthError;

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="System Configuration" subtitle="Current configuration thresholds and system health" />
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-40 bg-gray-800/50 rounded-xl border border-gray-700/50 skeleton-shimmer" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="System Configuration" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (!config) return null;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="System Configuration"
        subtitle="Current configuration thresholds and system health"
      />

      {health && (
        <div className={`rounded-xl border p-5 ${
          health.status === 'healthy'
            ? 'bg-emerald-500/10 border-emerald-500/20'
            : 'bg-yellow-500/10 border-yellow-500/20'
        }`}>
          <div className="flex items-center gap-3">
            <span className="text-2xl">
              {health.status === 'healthy' ? '✅' : '⚠️'}
            </span>
            <div>
              <h3 className="font-semibold text-gray-100">
                System {health.status === 'healthy' ? 'Healthy' : 'Degraded'}
              </h3>
              <p className="text-sm text-gray-400">
                Database: {health.database} · {health.total_claims} claims stored
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-4">
        <ConfigTable
          title="Escalation (Human-in-the-Loop)"
          icon="🔔"
          config={config.escalation ?? {}}
          descriptions={ESCALATION_DESCRIPTIONS}
        />
        <ConfigTable
          title="Fraud Detection"
          icon="🚨"
          config={config.fraud ?? {}}
          descriptions={FRAUD_DESCRIPTIONS}
        />
        <ConfigTable
          title="Vehicle Valuation"
          icon="💰"
          config={config.valuation ?? {}}
        />
        <ConfigTable
          title="Partial Loss"
          icon="🔧"
          config={config.partial_loss ?? {}}
        />
        <ConfigTable
          title="Token Budgets"
          icon="🎫"
          config={config.token_budgets ?? {}}
        />
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
            <span>⚙️</span> General
          </h3>
          <p className="text-sm text-gray-400">
            CrewAI Verbose Mode:{' '}
            <span className="font-mono font-medium text-blue-400">
              {config.crew_verbose ? 'true' : 'false'}
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}
