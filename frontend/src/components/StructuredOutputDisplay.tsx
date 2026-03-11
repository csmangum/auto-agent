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

function parseEscalation(str: string): EscalationPayload | null {
  if (!str?.trim()) return null;
  try {
    const obj = JSON.parse(str) as Record<string, unknown>;
    const has =
      obj.escalation_reasons ||
      obj.reason ||
      obj.priority ||
      obj.recommended_action ||
      obj.indicators ||
      obj.fraud_indicators ||
      (obj.router_confidence != null && obj.router_confidence_threshold != null);
    return has ? (obj as EscalationPayload) : null;
  } catch {
    return null;
  }
}

function parseRouter(str: string): RouterPayload | null {
  if (!str?.trim()) return null;
  try {
    const obj = JSON.parse(str) as Record<string, unknown>;
    if ('claim_type' in obj || ('confidence' in obj && 'reasoning' in obj)) {
      return {
        claim_type: obj.claim_type as string,
        confidence: obj.confidence as number,
        reasoning: obj.reasoning as string,
      };
    }
    return null;
  } catch {
    return null;
  }
}

function parseStateSnapshot(str: string): StateSnapshot | null {
  if (!str?.trim()) return null;
  try {
    const obj = JSON.parse(str) as Record<string, unknown>;
    if ('status' in obj && ('claim_type' in obj || 'payout_amount' in obj)) {
      return {
        status: obj.status as string,
        claim_type: obj.claim_type as string | null,
        payout_amount: obj.payout_amount as number | null,
      };
    }
    return null;
  } catch {
    return null;
  }
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

function EscalationDisplay({
  parsed,
  variant = 'default',
}: {
  parsed: EscalationPayload;
  variant?: 'audit' | 'default';
}) {
  const reasons = parsed.escalation_reasons ?? [];
  const indicators = parsed.indicators ?? parsed.fraud_indicators ?? [];
  const priority = parsed.priority;
  const recommended = parsed.recommended_action;
  const reason = parsed.reason;
  const v = variant;
  const isAudit = v === 'audit';

  const priorityBlock = priority && (
    <DetailRow label="Priority" variant={v}>
      <DetailBadge
        className={PRIORITY_BADGE_STYLES[priority] ?? DEFAULT_PRIORITY_STYLE}
      >
        {priority}
      </DetailBadge>
    </DetailRow>
  );
  const reasonsBlock =
    reasons.length > 0 && (
      <DetailRow label="Reasons" variant={v}>
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
      </DetailRow>
    );
  const indicatorsBlock =
    indicators.length > 0 && (
      <DetailRow
        label={parsed.indicators ? 'Indicators' : 'Fraud indicators'}
        variant={v}
      >
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
      </DetailRow>
    );
  const reasonBlock =
    reason && (
      <DetailRow label="Reason" variant={v}>
        <span className="text-gray-400">{reason}</span>
      </DetailRow>
    );
  const routerBlock =
    parsed.router_confidence != null &&
    parsed.router_confidence_threshold != null && (
      <DetailRow label="Router" variant={v}>
        <span className="text-gray-400">
          Confidence {parsed.router_confidence} below threshold{' '}
          {parsed.router_confidence_threshold}
        </span>
      </DetailRow>
    );

  if (isAudit) {
    return (
      <div className="space-y-4">
        {(priority || reasons.length > 0) && (
          <div className="space-y-3">
            {priorityBlock}
            {reasonsBlock}
          </div>
        )}
        {indicatorsBlock}
        {reasonBlock}
        {routerBlock}
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
        {priorityBlock}
        {reasonsBlock}
        {indicatorsBlock}
        {reasonBlock}
        {routerBlock}
      </div>
      {recommended && (
        <p className="text-sm text-gray-400 pt-0.5 border-t border-gray-700/50">
          {recommended}
        </p>
      )}
    </div>
  );
}

function RouterDisplay({ parsed }: { parsed: RouterPayload }) {
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
  value: string;
  compact?: boolean;
  variant?: 'audit' | 'default';
  /** Max chars for fallback raw display. Omit for no truncation (e.g. scrollable workflow output). */
  maxLength?: number;
}) {
  if (!value?.trim()) return <span className="text-gray-500">—</span>;

  const escalation = parseEscalation(value);
  const stateSnapshot = parseStateSnapshot(value);
  const router = parseRouter(value);

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
        <RouterDisplay parsed={router} />
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
