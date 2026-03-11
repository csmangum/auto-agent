import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
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

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter initialEntries={['/claims']}>{children}</MemoryRouter>;
}

describe('ClaimTable', () => {
  it('shows empty state when no claims', () => {
    render(
      <TestWrapper>
        <ClaimTable claims={[]} />
      </TestWrapper>
    );
    expect(screen.getByText('No claims found')).toBeInTheDocument();
    expect(screen.getByText('Submit a Claim')).toBeInTheDocument();
  });

  it('shows filter-specific empty state when hasFilters is true', () => {
    render(
      <TestWrapper>
        <ClaimTable claims={[]} hasFilters />
      </TestWrapper>
    );
    expect(screen.getByText('No claims found')).toBeInTheDocument();
    expect(screen.queryByText('Submit a Claim')).not.toBeInTheDocument();
  });

  it('renders claim rows', () => {
    render(
      <TestWrapper>
        <ClaimTable claims={mockClaims} />
      </TestWrapper>
    );
    expect(screen.getByText('CLM-001')).toBeInTheDocument();
    expect(screen.getByText('POL-001')).toBeInTheDocument();
    expect(screen.getByText('new')).toBeInTheDocument();
  });

  it('claim rows are clickable', () => {
    render(
      <TestWrapper>
        <ClaimTable claims={mockClaims} />
      </TestWrapper>
    );
    const row = screen.getByText('CLM-001').closest('tr');
    expect(row).toHaveClass('cursor-pointer');
    fireEvent.click(row!);
  });
});
