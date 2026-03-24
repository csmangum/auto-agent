import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ThirdPartyPortalLiabilityPanel } from './ThirdPartyPortalLiabilityPanel';
import type { Claim } from '../../api/types';

function makeClaim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: 'CLM-1',
    status: 'settled',
    claim_type: 'partial_loss',
    claimant_name: 'Test',
    policy_number: 'POL-1',
    vin: 'VIN123',
    vehicle_year: 2022,
    vehicle_make: 'Honda',
    vehicle_model: 'Accord',
    incident_date: '2025-01-01',
    incident_description: 'Collision',
    damage_description: 'Front bumper',
    ...overrides,
  } as Claim;
}

describe('ThirdPartyPortalLiabilityPanel', () => {
  const disputableStatuses = ['settled', 'open'];

  it('renders claim status and type', () => {
    render(
      <ThirdPartyPortalLiabilityPanel
        claim={makeClaim()}
        disputableStatuses={disputableStatuses}
        onSubmitDispute={vi.fn()}
      />
    );
    expect(screen.getByText('settled')).toBeInTheDocument();
    expect(screen.getByText('partial loss')).toBeInTheDocument();
  });

  it('shows liability percentage when present', () => {
    render(
      <ThirdPartyPortalLiabilityPanel
        claim={makeClaim({ liability_percentage: 75 })}
        disputableStatuses={disputableStatuses}
        onSubmitDispute={vi.fn()}
      />
    );
    expect(screen.getByText('75%')).toBeInTheDocument();
  });

  it('shows payout amount when present', () => {
    render(
      <ThirdPartyPortalLiabilityPanel
        claim={makeClaim({ payout_amount: 5000 })}
        disputableStatuses={disputableStatuses}
        onSubmitDispute={vi.fn()}
      />
    );
    expect(screen.getByText('$5,000')).toBeInTheDocument();
  });

  it('disables dispute form when status is not disputable', () => {
    render(
      <ThirdPartyPortalLiabilityPanel
        claim={makeClaim({ status: 'closed' })}
        disputableStatuses={disputableStatuses}
        onSubmitDispute={vi.fn()}
      />
    );
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByText(/Liability disputes can only be filed/)).toBeInTheDocument();
  });

  it('shows dispute form when status is disputable', () => {
    render(
      <ThirdPartyPortalLiabilityPanel
        claim={makeClaim({ status: 'settled' })}
        disputableStatuses={disputableStatuses}
        onSubmitDispute={vi.fn()}
      />
    );
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Submit Liability Dispute' })
    ).toBeInTheDocument();
  });

  it('submits dispute and shows result', async () => {
    const onSubmitDispute = vi.fn().mockResolvedValue('Dispute accepted');
    render(
      <ThirdPartyPortalLiabilityPanel
        claim={makeClaim({ status: 'open' })}
        disputableStatuses={disputableStatuses}
        onSubmitDispute={onSubmitDispute}
      />
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'I have dash cam footage' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Submit Liability Dispute' }));

    await waitFor(() => {
      expect(onSubmitDispute).toHaveBeenCalledWith('I have dash cam footage');
      expect(screen.getByText('Dispute accepted')).toBeInTheDocument();
    });
  });

  it('shows error on dispute failure', async () => {
    const onSubmitDispute = vi.fn().mockRejectedValue(new Error('Server error'));
    render(
      <ThirdPartyPortalLiabilityPanel
        claim={makeClaim()}
        disputableStatuses={disputableStatuses}
        onSubmitDispute={onSubmitDispute}
      />
    );

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'evidence' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit Liability Dispute' }));

    await waitFor(() => {
      expect(screen.getByText('Error: Server error')).toBeInTheDocument();
    });
  });
});
