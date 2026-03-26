import { describe, it, expect } from 'vitest';
import { formatClaimBreadcrumbLabel } from './claimBreadcrumbLabel';
import type { Claim } from '../api/types';

function baseClaim(over: Partial<Claim> = {}): Claim {
  return {
    id: 'c-1',
    policy_number: 'POL-99',
    vin: 'VIN123',
    status: 'open',
    ...over,
  };
}

describe('formatClaimBreadcrumbLabel', () => {
  it('uses policy and vehicle when present', () => {
    expect(
      formatClaimBreadcrumbLabel(
        baseClaim({ vehicle_year: 2021, vehicle_make: 'Honda', vehicle_model: 'Civic' })
      )
    ).toBe('POL-99 · 2021 Honda Civic');
  });

  it('uses policy only when no vehicle fields', () => {
    expect(formatClaimBreadcrumbLabel(baseClaim())).toBe('POL-99');
  });

  it('falls back to id when policy_number empty', () => {
    expect(formatClaimBreadcrumbLabel(baseClaim({ policy_number: '   ' }))).toBe('c-1');
  });
});
