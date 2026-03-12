import type { ReactNode } from 'react';
import PageHeader from '../components/PageHeader';
import { useSystemConfig, useSystemHealth } from '../api/queries';
import { WarningIcon, BellIcon, FraudIcon, CurrencyIcon, PartialLossIcon, TokenIcon, SystemIcon } from '../components/icons';

interface ConfigTableProps {
  title: string;
  icon?: ReactNode;
  config: Record<string, unknown>;
  descriptions?: Record<string, string>;
  cardClass?: string;
}

function ConfigTable({ title, icon, config, descriptions = {}, cardClass }: ConfigTableProps) {
  const entries = Object.entries(config ?? {});
  if (entries.length === 0) return null;

  const baseCard = 'rounded-xl border p-5';
  const classes = cardClass ?? 'bg-gray-800/50 border-gray-700/50';

  return (
    <div className={`${baseCard} ${classes}`}>
      <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
        {icon}
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
      <div className="space-y-8 animate-fade-in">
        <PageHeader title="System Configuration" subtitle="Current configuration thresholds and system health" />
        <div className="h-24 rounded-xl border border-gray-700/50 bg-gray-800/50 skeleton-shimmer" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="pb-8 last:pb-0">
            <div className="flex items-center gap-2 pb-3 border-b border-gray-700/50 mb-4">
              <div className="h-4 w-4 rounded bg-gray-700/50 skeleton-shimmer" />
              <div className="h-4 w-36 rounded bg-gray-700/50 skeleton-shimmer" />
            </div>
            <div className="h-48 rounded-xl border border-gray-700/50 bg-gray-800/50 skeleton-shimmer mt-4" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="System Configuration" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <WarningIcon className="w-5 h-5 shrink-0 text-red-400" aria-hidden />
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (!config) return null;

  return (
    <div className="space-y-8 animate-fade-in">
      <PageHeader
        title="System Configuration"
        subtitle="Current configuration thresholds and system health"
      />

      {health && (
        <section className="pb-8">
          <h2 className="text-base font-semibold text-gray-200 pb-3 border-b border-gray-700/50 flex items-center gap-2">
            <span className="text-gray-500" aria-hidden>➤</span>
            {health.status === 'healthy' ? (
              <span className="w-5 h-5 rounded-full bg-emerald-500/30 flex items-center justify-center" aria-hidden>
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
              </span>
            ) : (
              <WarningIcon className="w-5 h-5 shrink-0 text-amber-400" aria-hidden />
            )}
            System health
          </h2>
          <div
            className={`rounded-xl border border-l-4 p-5 mt-4 ${
              health.status === 'healthy'
                ? 'bg-emerald-500/10 border-emerald-500/30 border-l-emerald-500/60'
                : 'bg-amber-500/10 border-amber-500/30 border-l-amber-500/60'
            }`}
          >
            <h3 className="font-semibold text-gray-100">
              System {health.status === 'healthy' ? 'Healthy' : 'Degraded'}
            </h3>
            <p className="text-sm text-gray-400 mt-0.5">
              Database: {health.database} · {health.total_claims} claims stored
            </p>
          </div>
        </section>
      )}

      <section className="pb-8 last:pb-0">
        <h2 className="text-base font-semibold text-gray-200 pb-3 border-b border-gray-700/50 flex items-center gap-2">
          <span className="text-gray-500" aria-hidden>➤</span>
          <SystemIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />
          Configuration
        </h2>
        <div className="space-y-4 mt-4">
          <ConfigTable
            title="Escalation (Human-in-the-Loop)"
            icon={<BellIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />}
            config={config.escalation ?? {}}
            descriptions={ESCALATION_DESCRIPTIONS}
            cardClass="bg-amber-500/10 border-amber-500/30 border-l-4 border-l-amber-500/60"
          />
          <ConfigTable
            title="Fraud Detection"
            icon={<FraudIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />}
            config={config.fraud ?? {}}
            descriptions={FRAUD_DESCRIPTIONS}
            cardClass="bg-red-500/10 border-red-500/30 border-l-4 border-l-red-500/60"
          />
          <ConfigTable
            title="Vehicle Valuation"
            icon={<CurrencyIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />}
            config={config.valuation ?? {}}
            cardClass="bg-emerald-500/10 border-emerald-500/30 border-l-4 border-l-emerald-500/60"
          />
          <ConfigTable
            title="Partial Loss"
            icon={<PartialLossIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />}
            config={config.partial_loss ?? {}}
            cardClass="bg-teal-500/10 border-teal-500/30 border-l-4 border-l-teal-500/60"
          />
          <ConfigTable
            title="Token Budgets"
            icon={<TokenIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />}
            config={config.token_budgets ?? {}}
            cardClass="bg-purple-500/10 border-purple-500/30 border-l-4 border-l-purple-500/60"
          />
          <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 border-l-4 border-l-gray-500/60 p-5">
            <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
              <SystemIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />
              General
            </h3>
            <p className="text-sm text-gray-400">
              CrewAI Verbose Mode:{' '}
              <span className="font-mono font-medium text-blue-400">
                {config.crew_verbose ? 'true' : 'false'}
              </span>
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
