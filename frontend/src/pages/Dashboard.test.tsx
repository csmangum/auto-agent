import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Dashboard from './Dashboard';

const mockStats = {
  total_claims: 100,
  by_status: { pending: 5, processing: 10, open: 20, closed: 50, settled: 15 },
  by_type: { new: 80, duplicate: 20 },
  total_audit_events: 200,
  total_workflow_runs: 50,
};

const mockClaimsData = {
  claims: [
    {
      id: 'CLM-001',
      policy_number: 'POL-001',
      vin: '1HGBH41JXMN109186',
      status: 'open',
      claim_type: 'new',
      created_at: '2025-01-15 10:00:00',
    },
  ],
  total: 1,
  limit: 10,
  offset: 0,
};

vi.mock('../api/queries', () => ({
  useClaimsStats: vi.fn(),
  useClaims: vi.fn(),
}));

const { useClaimsStats, useClaims } = await import('../api/queries');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>{children}</BrowserRouter>
      </QueryClientProvider>
    );
  };
}

describe('Dashboard', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useClaimsStats).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useClaims).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: null,
    } as never);
  });

  it('shows loading state when stats or claims loading', () => {
    vi.mocked(useClaimsStats).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);
    vi.mocked(useClaims).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>
    );
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows error state when API fails', () => {
    vi.mocked(useClaimsStats).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Network error'),
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>
    );
    expect(screen.getByText('Error loading dashboard')).toBeInTheDocument();
    expect(screen.getByText('Network error')).toBeInTheDocument();
  });

  it('renders stats and recent claims when data loaded', () => {
    vi.mocked(useClaimsStats).mockReturnValue({
      data: mockStats,
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>
    );
    expect(screen.getByText('Total Claims')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Recent Claims')).toBeInTheDocument();
    expect(screen.getByText('CLM-001')).toBeInTheDocument();
  });

  it('renders quick action links', () => {
    vi.mocked(useClaimsStats).mockReturnValue({
      data: mockStats,
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>
    );
    expect(screen.getByRole('link', { name: /new claim/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /review queue/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /view agents/i })).toBeInTheDocument();
  });
});
