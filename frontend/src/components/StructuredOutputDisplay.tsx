import StatusBadge from './StatusBadge';
import TypeBadge from './TypeBadge';

const PRIORITY_BADGE_STYLES: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-300 ring-red-500/30',
  high: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  medium: 'bg-yellow-500/20 text-yellow-300 ring-yellow-500/30',
  low: 'bg-gray-500/20 text-gray-400 ring-gray-500/30',
};

const DEFAULT_PRIORITY_STYLE = 'bg-yellow-500/20 text-yellow-300 ring-yellow-500/30';

interface EscalationPayload {
  escalation_reasons?: string[];
  reason?: string;
  priority?: string;
  recommended_action?: string;
  indicators?: string[];
  fraud_indicators?: string[];
  router_confidence?: number;
  router_confidence_threshold?: number;
  router_claim_type?: string;
  router_reasoning?: string;
}

interface RouterPayload {
  claim_type?: string;
  confidence?: number;
  reasoning?: string;
}

interface StateSnapshot {
  status?: string;
  claim_type?: string | null;
  payout_amount?: number | null;
}

function normalizeStringArray(value: unknown): string[] | undefined {
  if (Array.isArray(value)) {
    const strings = value.filter((v): v is string => typeof v === 'string');
    return strings.length ? strings : undefined;
  }
  if (typeof value === 'string') return [value];
  return undefined;
}

function parseEscalation(obj: Record<string, unknown>): EscalationPayload | null {
  const escalation_reasons = normalizeStringArray(obj.escalation_reasons);
  const indicators = normalizeStringArray(obj.indicators);
  const fraud_indicators = normalizeStringArray(obj.fraud_indicators);
  const reason = typeof obj.reason === 'string' ? obj.reason : undefined;
  const priority = typeof obj.priority === 'string' ? obj.priority : undefined;
  const recommended_action =
    typeof obj.recommended_action === 'string' ? obj.recommended_action : undefined;
  const router_claim_type =
    typeof obj.router_claim_type === 'string' ? obj.router_claim_type : undefined;
  const router_reasoning =
    typeof obj.router_reasoning === 'string' ? obj.router_reasoning : undefined;
  const router_confidence =
    typeof obj.router_confidence === 'number' ? obj.router_confidence : undefined;
  const router_confidence_threshold =
    typeof obj.router_confidence_threshold === 'number'
      ? obj.router_confidence_threshold
      : undefined;

  const hasSpecificEscalation =
    (escalation_reasons && escalation_reasons.length > 0) ||
    !!recommended_action ||
    (indicators && indicators.length > 0) ||
    (fraud_indicators && fraud_indicators.length > 0) ||
    (router_confidence != null && router_confidence_threshold != null);

  if (hasSpecificEscalation) {
    return {
      escalation_reasons,
      reason,
      priority,
      recommended_action,
      indicators,
      fraud_indicators,
      router_confidence,
      router_confidence_threshold,
      router_claim_type,
      router_reasoning,
    };
  }

  if ('status' in obj && ('claim_type' in obj || 'payout_amount' in obj)) return null;

  const hasGeneric = !!reason || !!priority;
  if (!hasGeneric) return null;

  return {
    escalation_reasons,
    reason,
    priority,
    recommended_action,
    indicators,
    fraud_indicators,
    router_confidence,
    router_confidence_threshold,
    router_claim_type,
    router_reasoning,
  };
}

function parseRouter(obj: Record<string, unknown>): RouterPayload | null {
  if ('claim_type' in obj || ('confidence' in obj && 'reasoning' in obj)) {
    return {
      claim_type: typeof obj.claim_type === 'string' ? obj.claim_type : undefined,
      confidence: typeof obj.confidence === 'number' ? obj.confidence : undefined,
      reasoning: typeof obj.reasoning === 'string' ? obj.reasoning : undefined,
    };
  }
  return null;
}

function parseStateSnapshot(obj: Record<string, unknown>): StateSnapshot | null {
  if (!('status' in obj) || (!('claim_type' in obj) && !('payout_amount' in obj))) {
    return null;
  }
  const result: StateSnapshot = {};
  if ('status' in obj) result.status = obj.status as string;
  if ('claim_type' in obj) result.claim_type = obj.claim_type as string | null;
  if ('payout_amount' in obj) result.payout_amount = obj.payout_amount as number | null;
  return result;
}

function DetailBadge({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ring-1 ring-inset ${className ?? 'bg-gray-600/30 text-gray-400 ring-gray-500/30'}`}
    >
      {children}
    </span>
  );
}

function DetailRow({
  label,
  children,
  variant,
}: {
  label: string;
  children: React.ReactNode;
  variant?: 'audit' | 'default';
}) {
  if (variant === 'audit') {
    return (
      <div className="space-y-1">
        <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500">
          {label}
        </p>
        <div className="text-sm">{children}</div>
      </div>
    );
  }
  return (
    <>
      <span className="text-gray-500 shrink-0 text-sm">{label}</span>
      <span className="text-sm">{children}</span>
    </>
  );
}

function EscalationRowContent({
  parsed,
  variant,
}: {
  parsed: EscalationPayload;
  variant: 'audit' | 'default';
}) {
  const reasons = parsed.escalation_reasons ?? [];
  const indicators = parsed.indicators ?? parsed.fraud_indicators ?? [];
  const priority = parsed.priority;
  const reason = parsed.reason;
  const rowVariant = variant === 'audit' ? ('audit' as const) : undefined;

  const priorityBadge = priority ? (
    <DetailBadge
      className={PRIORITY_BADGE_STYLES[priority] ?? DEFAULT_PRIORITY_STYLE}
    >
      {priority}
    </DetailBadge>
  ) : null;

  const reasonsContent =
    reasons.length > 0 ? (
      <div className="flex flex-wrap gap-1">
        {reasons.map((r) => (
          <DetailBadge
            key={r}
            className="bg-purple-500/20 text-purple-300 ring-purple-500/30"
          >
            {r.replace(/_/g, ' ')}
          </DetailBadge>
        ))}
      </div>
    ) : null;

  const indicatorsContent =
    indicators.length > 0 ? (
      <div className="flex flex-wrap gap-1">
        {indicators.map((i) => (
          <DetailBadge
            key={i}
            className="bg-red-500/20 text-red-300 ring-red-500/30"
          >
            {i.replace(/_/g, ' ')}
          </DetailBadge>
        ))}
      </div>
    ) : null;

  const routerContent =
    parsed.router_confidence != null &&
    parsed.router_confidence_threshold != null ? (
      <span className="text-gray-400">
        Confidence {parsed.router_confidence} below threshold{' '}
        {parsed.router_confidence_threshold}
      </span>
    ) : null;

  const rows = [
    priority && { label: 'Priority', children: priorityBadge },
    reasons.length > 0 && {
      label: 'Reasons',
      children: reasonsContent,
    },
    indicators.length > 0 && {
      label: parsed.indicators ? 'Indicators' : 'Fraud indicators',
      children: indicatorsContent,
    },
    reason && { label: 'Reason', children: <span className="text-gray-400">{reason}</span> },
    routerContent && { label: 'Router', children: routerContent },
  ].filter(Boolean) as { label: string; children: React.ReactNode }[];

  return (
    <>
      {rows.map(({ label, children }) => (
        <DetailRow key={label} label={label} variant={rowVariant}>
          {children}
        </DetailRow>
      ))}
    </>
  );
}

function EscalationDisplay({
  parsed,
  variant = 'default',
}: {
  parsed: EscalationPayload;
  variant?: 'audit' | 'default';
}) {
  const recommended = parsed.recommended_action;
  const isAudit = variant === 'audit';

  if (isAudit) {
    return (
      <div className="space-y-4">
        <EscalationRowContent parsed={parsed} variant="audit" />
        {recommended && (
          <div className="rounded-md bg-amber-500/10 border border-amber-500/20 p-3">
            <p className="text-[10px] font-medium uppercase tracking-wider text-amber-400/80 mb-1">
              Recommended action
            </p>
            <p className="text-sm text-gray-300">{recommended}</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
        <EscalationRowContent parsed={parsed} variant="default" />
      </div>
      {recommended && (
        <p className="text-sm text-gray-400 pt-0.5 border-t border-gray-700/50">
          {recommended}
        </p>
      )}
    </div>
  );
}

function RouterDisplay({
  parsed,
  variant = 'default',
}: {
  parsed: RouterPayload;
  variant?: 'audit' | 'default';
}) {
  const isAudit = variant === 'audit';

  if (isAudit) {
    return (
      <div className="space-y-3">
        {parsed.claim_type && (
          <DetailRow label="Claim type" variant="audit">
            <TypeBadge type={parsed.claim_type} />
          </DetailRow>
        )}
        {parsed.confidence != null && (
          <DetailRow label="Confidence" variant="audit">
            <span className="text-gray-400">
              {(parsed.confidence <= 1 ? parsed.confidence * 100 : parsed.confidence).toFixed(0)}%
            </span>
          </DetailRow>
        )}
        {parsed.reasoning && (
          <DetailRow label="Reasoning" variant="audit">
            <p className="text-gray-400">{parsed.reasoning}</p>
          </DetailRow>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
      {parsed.claim_type && (
        <>
          <span className="text-gray-500 shrink-0">Claim type</span>
          <span>
            <TypeBadge type={parsed.claim_type} />
          </span>
        </>
      )}
      {parsed.confidence != null && (
        <>
          <span className="text-gray-500 shrink-0">Confidence</span>
          <span className="text-gray-400">
            {(parsed.confidence <= 1 ? parsed.confidence * 100 : parsed.confidence).toFixed(0)}%
          </span>
        </>
      )}
      {parsed.reasoning && (
        <>
          <span className="text-gray-500 shrink-0">Reasoning</span>
          <p className="text-gray-400">{parsed.reasoning}</p>
        </>
      )}
    </div>
  );
}

function StateSnapshotDisplay({
  parsed,
  variant = 'default',
}: {
  parsed: StateSnapshot;
  variant?: 'audit' | 'default';
}) {
  const isAudit = variant === 'audit';

  if (isAudit) {
    return (
      <div className="space-y-3">
        {parsed.status != null && (
          <DetailRow label="Status" variant="audit">
            <StatusBadge status={parsed.status} />
          </DetailRow>
        )}
        {'claim_type' in parsed && (
          <DetailRow label="Claim type" variant="audit">
            {parsed.claim_type ? (
              <TypeBadge type={parsed.claim_type} />
            ) : (
              <span className="text-gray-400">—</span>
            )}
          </DetailRow>
        )}
        {'payout_amount' in parsed && (
          <DetailRow label="Payout" variant="audit">
            <span className="text-gray-400">
              {parsed.payout_amount != null
                ? `$${parsed.payout_amount.toLocaleString()}`
                : '—'}
            </span>
          </DetailRow>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
      {parsed.status != null && (
        <>
          <span className="text-gray-500 shrink-0">Status</span>
          <span>
            <StatusBadge status={parsed.status} />
          </span>
        </>
      )}
      {'claim_type' in parsed && (
        <>
          <span className="text-gray-500 shrink-0">Claim type</span>
          <span>
            {parsed.claim_type ? (
              <TypeBadge type={parsed.claim_type} />
            ) : (
              <span className="text-gray-400">—</span>
            )}
          </span>
        </>
      )}
      {'payout_amount' in parsed && (
        <>
          <span className="text-gray-500 shrink-0">Payout</span>
          <span className="text-gray-400">
            {parsed.payout_amount != null
              ? `$${parsed.payout_amount.toLocaleString()}`
              : '—'}
          </span>
        </>
      )}
    </div>
  );
}

/**
 * Parses JSON and renders structured UIs for known payload shapes.
 * Parse precedence (first match wins): escalation → state snapshot → router.
 * Unrecognized JSON or plain text falls through to raw display.
 */
export default function StructuredOutputDisplay({
  value,
  compact = false,
  variant = 'default',
  maxLength,
}: {
  value: string | undefined;
  compact?: boolean;
  variant?: 'audit' | 'default';
  /** Max chars for fallback raw display. Omit for no truncation (e.g. scrollable workflow output). */
  maxLength?: number;
}) {
  if (!value?.trim()) return <span className="text-gray-500">—</span>;

  let parsed: Record<string, unknown> | null = null;
  try {
    parsed = JSON.parse(value) as Record<string, unknown>;
  } catch {
    // Fall through to raw display
  }

  const escalation = parsed ? parseEscalation(parsed) : null;
  const stateSnapshot = parsed ? parseStateSnapshot(parsed) : null;
  const router = parsed ? parseRouter(parsed) : null;

  if (escalation) {
    return (
      <div className={compact ? '' : 'mt-2'}>
        <EscalationDisplay parsed={escalation} variant={variant} />
      </div>
    );
  }

  if (stateSnapshot) {
    return (
      <div className={compact ? '' : 'mt-2'}>
        <StateSnapshotDisplay parsed={stateSnapshot} variant={variant} />
      </div>
    );
  }

  if (router) {
    return (
      <div className={compact ? '' : 'mt-2'}>
        <RouterDisplay parsed={router} variant={variant} />
      </div>
    );
  }

  const displayValue =
    maxLength != null && value.length > maxLength
      ? value.slice(0, maxLength) + '…'
      : value;

  return (
    <div className="text-sm text-gray-400 break-words whitespace-pre-wrap font-mono">
      {displayValue}
    </div>
  );
}
