import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import CoverageSummary from './CoverageSummary';

vi.mock('../api/queries', () => ({
  usePolicies: vi.fn(),
}));

const { usePolicies } = await import('../api/queries');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

const mockPolicy = {
  policy_number: 'POL-001',
  status: 'active',
  vehicle_count: 2,
  liability_limits: { bi_per_accident: 100000, pd_per_accident: 50000 },
  collision_deductible: 500,
  comprehensive_deductible: 250,
  vehicles: [
    { vin: '1HGBH41JXMN109186', vehicle_year: 2020, vehicle_make: 'Honda', vehicle_model: 'Accord' },
    { vin: 'WVWZZZ3CZWE123456', vehicle_year: 2021, vehicle_make: 'Volkswagen', vehicle_model: 'Golf' },
  ],
};

describe('CoverageSummary', () => {
  beforeEach(() => {
    vi.mocked(usePolicies).mockReturnValue({
      data: { policies: [mockPolicy] },
      isLoading: false,
      error: null,
    } as ReturnType<typeof usePolicies>);
  });

  it('renders policy details', () => {
    render(
      <CoverageSummary policyNumber="POL-001" vin="1HGBH41JXMN109186" claimType="partial_loss" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Policy Details')).toBeInTheDocument();
    expect(screen.getByText('POL-001')).toBeInTheDocument();
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('renders coverage limits', () => {
    render(
      <CoverageSummary policyNumber="POL-001" vin="1HGBH41JXMN109186" claimType="partial_loss" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Coverage Limits')).toBeInTheDocument();
    expect(screen.getByText('$100,000')).toBeInTheDocument();
    expect(screen.getByText('$50,000')).toBeInTheDocument();
    expect(screen.getByText('$500')).toBeInTheDocument();
    expect(screen.getByText('$250')).toBeInTheDocument();
  });

  it('highlights matching vehicle', () => {
    render(
      <CoverageSummary policyNumber="POL-001" vin="1HGBH41JXMN109186" claimType="partial_loss" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('✓ Claim Vehicle')).toBeInTheDocument();
    expect(screen.getByText('2020 Honda Accord')).toBeInTheDocument();
  });

  it('shows relevant coverage indicators for partial_loss', () => {
    render(
      <CoverageSummary policyNumber="POL-001" vin="1HGBH41JXMN109186" claimType="partial_loss" />,
      { wrapper: createWrapper() }
    );
    const relevantIndicators = screen.getAllByText('✓ Relevant to this claim');
    expect(relevantIndicators.length).toBeGreaterThanOrEqual(1);
  });

  it('shows policy not found for unknown policy', () => {
    render(
      <CoverageSummary policyNumber="POL-UNKNOWN" vin="1HGBH41JXMN109186" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Policy not found')).toBeInTheDocument();
  });

  it('renders loading state', () => {
    vi.mocked(usePolicies).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof usePolicies>);

    render(
      <CoverageSummary policyNumber="POL-001" vin="1HGBH41JXMN109186" />,
      { wrapper: createWrapper() }
    );
    // Should show skeleton loading
    expect(document.querySelector('.skeleton-shimmer')).toBeTruthy();
  });

  it('renders error state', () => {
    vi.mocked(usePolicies).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load'),
    } as ReturnType<typeof usePolicies>);

    render(
      <CoverageSummary policyNumber="POL-001" vin="1HGBH41JXMN109186" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Failed to load')).toBeInTheDocument();
  });
});
