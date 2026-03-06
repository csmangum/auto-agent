import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import ClaimTable from './ClaimTable';
import type { Claim } from '../api/types';

const mockClaims: Claim[] = [
  {
    id: 'CLM-001',
    policy_number: 'POL-001',
    vin: '1HGBH41JXMN109186',
    status: 'open',
    claim_type: 'new',
    created_at: '2025-01-15 10:00:00',
  },
];

describe('ClaimTable', () => {
  it('shows empty message when no claims', () => {
    render(
      <BrowserRouter>
        <ClaimTable claims={[]} />
      </BrowserRouter>
    );
    expect(screen.getByText('No claims found.')).toBeInTheDocument();
  });

  it('renders claim rows', () => {
    render(
      <BrowserRouter>
        <ClaimTable claims={mockClaims} />
      </BrowserRouter>
    );
    expect(screen.getByText('CLM-001')).toBeInTheDocument();
    expect(screen.getByText('POL-001')).toBeInTheDocument();
    expect(screen.getByText('new')).toBeInTheDocument();
  });
});
