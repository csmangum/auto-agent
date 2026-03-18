import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import CostDashboard from './CostDashboard';
import type { CostBreakdown } from '../api/client';

vi.mock('../api/queries', () => ({
  useCostBreakdown: vi.fn(),
}));

const { useCostBreakdown } = await import('../api/queries');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

const mockCostBreakdown: CostBreakdown = {
  global_stats: {
    total_claims: 5,
    total_llm_calls: 42,
    total_tokens: 12500,
    total_cost_usd: 0.0523,
    avg_cost_per_claim: 0.01046,
    avg_tokens_per_claim: 2500,
    by_crew: {},
    by_claim_type: {},
  },
  by_crew: {
    router: { total_cost_usd: 0.01, total_tokens: 2000, total_calls: 2 },
    partial_loss: { total_cost_usd: 0.03, total_tokens: 8000, total_calls: 15 },
  },
  by_claim_type: {
    partial_loss: {
      total_cost_usd: 0.04,
      total_tokens: 10000,
      total_claims: 3,
      total_calls: 20,
    },
  },
  daily: {
    '2025-03-17': { total_cost_usd: 0.05, total_tokens: 12000, claims: 4 },
  },
  total_cost_usd: 0.0523,
  total_tokens: 12500,
};

describe('CostDashboard', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useCostBreakdown).mockReturnValue({
      data: mockCostBreakdown,
      isLoading: false,
      error: null,
    } as never);
  });

  it('renders cost dashboard with populated data', () => {
    render(
      <Wrapper>
        <CostDashboard />
      </Wrapper>
    );
    expect(screen.getByText('LLM Cost Dashboard')).toBeInTheDocument();
    expect(screen.getByText(/Token and cost attribution by crew, claim type, and daily spend/)).toBeInTheDocument();
    expect(screen.getByText('$0.0523')).toBeInTheDocument();
    expect(screen.getByText('12,500')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Cost by Crew')).toBeInTheDocument();
    expect(screen.getByText('Cost by Claim Type')).toBeInTheDocument();
    expect(screen.getByText('Daily Spend (last 14 days)')).toBeInTheDocument();
    expect(screen.getAllByText('partial loss').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('router')).toBeInTheDocument();
    expect(screen.getByText('2025-03-17')).toBeInTheDocument();
  });

  it('shows loading skeleton', () => {
    vi.mocked(useCostBreakdown).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <CostDashboard />
      </Wrapper>
    );
    expect(screen.getByText('LLM Cost Dashboard')).toBeInTheDocument();
    expect(document.querySelectorAll('.skeleton-shimmer').length).toBeGreaterThan(0);
  });

  it('shows error state', () => {
    vi.mocked(useCostBreakdown).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load cost data'),
    } as never);

    render(
      <Wrapper>
        <CostDashboard />
      </Wrapper>
    );
    expect(screen.getByText('LLM Cost Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Error loading cost data')).toBeInTheDocument();
    expect(screen.getByText('Failed to load cost data')).toBeInTheDocument();
  });

  it('shows empty state when no crew data', () => {
    vi.mocked(useCostBreakdown).mockReturnValue({
      data: {
        ...mockCostBreakdown,
        by_crew: {},
        by_claim_type: {},
        daily: {},
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <CostDashboard />
      </Wrapper>
    );
    expect(screen.getByText('No crew usage data yet. Process claims to see cost attribution.')).toBeInTheDocument();
    expect(screen.getByText('No claim-type data yet.')).toBeInTheDocument();
    expect(screen.getByText('No daily data yet.')).toBeInTheDocument();
  });

  it('formats cost with 4 decimal places', () => {
    render(
      <Wrapper>
        <CostDashboard />
      </Wrapper>
    );
    expect(screen.getByText('$0.0523')).toBeInTheDocument();
  });
});
