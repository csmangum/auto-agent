import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ThirdPartyPortalOverview } from './ThirdPartyPortalOverview';
import type { Claim, AuditEvent } from '../../api/types';

function makeClaim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: 'CLM-1',
    status: 'open',
    claim_type: 'partial_loss',
    claimant_name: 'Jane Doe',
    policy_number: 'POL-1',
    vin: 'VIN123',
    vehicle_year: 2022,
    vehicle_make: 'Toyota',
    vehicle_model: 'Camry',
    incident_date: '2025-03-01',
    incident_description: 'Rear-ended at stoplight',
    damage_description: 'Rear bumper',
    ...overrides,
  } as Claim;
}

describe('ThirdPartyPortalOverview', () => {
  it('renders vehicle info', () => {
    render(<ThirdPartyPortalOverview claim={makeClaim()} history={[]} />);
    expect(screen.getByText('2022 Toyota Camry')).toBeInTheDocument();
  });

  it('renders incident date', () => {
    render(<ThirdPartyPortalOverview claim={makeClaim()} history={[]} />);
    expect(screen.getByText('2025-03-01')).toBeInTheDocument();
  });

  it('renders status and type', () => {
    render(<ThirdPartyPortalOverview claim={makeClaim()} history={[]} />);
    expect(screen.getByText('open')).toBeInTheDocument();
    expect(screen.getByText('partial loss')).toBeInTheDocument();
  });

  it('shows payout amount with custom demand label', () => {
    render(
      <ThirdPartyPortalOverview
        claim={makeClaim({ payout_amount: 12000 })}
        history={[]}
        demandLabel="Subrogation Demand"
      />
    );
    expect(screen.getByText('Subrogation Demand')).toBeInTheDocument();
    expect(screen.getByText('$12,000')).toBeInTheDocument();
  });

  it('hides payout when null', () => {
    render(
      <ThirdPartyPortalOverview claim={makeClaim({ payout_amount: undefined })} history={[]} />
    );
    expect(screen.queryByText('Demand Amount')).not.toBeInTheDocument();
  });

  it('shows incident description', () => {
    render(<ThirdPartyPortalOverview claim={makeClaim()} history={[]} />);
    expect(screen.getByText('Rear-ended at stoplight')).toBeInTheDocument();
  });

  it('shows fallback when no description', () => {
    render(
      <ThirdPartyPortalOverview
        claim={makeClaim({ incident_description: undefined })}
        history={[]}
      />
    );
    expect(screen.getByText('No description available.')).toBeInTheDocument();
  });

  it('renders relevant history events', () => {
    const history: AuditEvent[] = [
      {
        id: 1,
        claim_id: 'CLM-1',
        action: 'status_changed',
        new_status: 'processing',
        created_at: '2025-03-02T10:00:00Z',
      } as AuditEvent,
      {
        id: 2,
        claim_id: 'CLM-1',
        action: 'note_added',
        created_at: '2025-03-02T11:00:00Z',
      } as AuditEvent,
    ];

    render(<ThirdPartyPortalOverview claim={makeClaim()} history={history} />);
    expect(screen.getByText('Key Events')).toBeInTheDocument();
    expect(screen.getByText('Status: processing')).toBeInTheDocument();
  });

  it('hides key events when no relevant history', () => {
    const history: AuditEvent[] = [
      {
        id: 1,
        claim_id: 'CLM-1',
        action: 'note_added',
        created_at: '2025-03-02T11:00:00Z',
      } as AuditEvent,
    ];
    render(<ThirdPartyPortalOverview claim={makeClaim()} history={history} />);
    expect(screen.queryByText('Key Events')).not.toBeInTheDocument();
  });
});
