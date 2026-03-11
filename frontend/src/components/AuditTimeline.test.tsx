import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import AuditTimeline from './AuditTimeline';
import type { AuditEvent } from '../api/types';

describe('AuditTimeline', () => {
  it('shows empty state when no events', () => {
    render(<AuditTimeline events={[]} />);
    expect(screen.getByText('No audit events')).toBeInTheDocument();
  });

  it('renders audit events', () => {
    const events: AuditEvent[] = [
      {
        claim_id: 'CLM-001',
        action: 'claim_created',
        created_at: '2025-01-15 10:00:00',
      },
    ];
    render(<AuditTimeline events={events} />);
    expect(screen.getByText('claim created')).toBeInTheDocument();
  });

  it('renders status change with before and after state sections', () => {
    const events: AuditEvent[] = [
      {
        claim_id: 'CLM-001',
        action: 'status_change',
        old_status: 'pending',
        new_status: 'open',
        before_state: '{"a":1}',
        after_state: '{"a":2}',
        created_at: '2025-01-15 10:00:00',
      },
    ];
    render(<AuditTimeline events={events} />);
    expect(screen.getByText('status change')).toBeInTheDocument();
    expect(screen.getByText('open')).toBeInTheDocument();
    expect(screen.getByText('Before')).toBeInTheDocument();
    expect(screen.getByText('After')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /show state diff/i })).not.toBeInTheDocument();
  });

  it('parses state snapshot JSON as table with status badge', () => {
    const events: AuditEvent[] = [
      {
        claim_id: 'CLM-001',
        action: 'status_change',
        old_status: 'pending',
        new_status: 'processing',
        details: '{"status": "processing", "claim_type": null, "payout_amount": null}',
        created_at: '2025-01-15 10:00:00',
      },
    ];
    render(<AuditTimeline events={events} />);
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Claim type')).toBeInTheDocument();
    expect(screen.getByText('Payout')).toBeInTheDocument();
    expect(screen.getAllByText('processing').length).toBeGreaterThanOrEqual(1);
  });

  it('renders escalation JSON as table with badges', () => {
    const events: AuditEvent[] = [
      {
        claim_id: 'CLM-001',
        action: 'status_change',
        old_status: 'processing',
        new_status: 'needs_review',
        details: JSON.stringify({
          escalation_reasons: ['fraud_suspected'],
          priority: 'critical',
          recommended_action: 'Review claim manually. Refer to SIU if fraud indicators are confirmed.',
          fraud_indicators: ['incident_damage_description_mismatch', 'multiple_claims_same_vin'],
        }),
        created_at: '2025-01-15 10:00:00',
      },
    ];
    render(<AuditTimeline events={events} />);
    expect(screen.getByText('Priority')).toBeInTheDocument();
    expect(screen.getByText('critical')).toBeInTheDocument();
    expect(screen.getByText('Reasons')).toBeInTheDocument();
    expect(screen.getByText('fraud suspected')).toBeInTheDocument();
    expect(screen.getByText(/Review claim manually/)).toBeInTheDocument();
    expect(screen.getByText('incident damage description mismatch')).toBeInTheDocument();
    expect(screen.getByText('multiple claims same vin')).toBeInTheDocument();
  });
});
