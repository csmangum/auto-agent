import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import SystemConfig from './SystemConfig';

vi.mock('../api/queries', () => ({
  useSystemConfig: vi.fn(),
  useSystemHealth: vi.fn(),
}));

const { useSystemConfig, useSystemHealth } = await import('../api/queries');

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

describe('SystemConfig', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useSystemConfig).mockReturnValue({
      data: {
        escalation: { confidence_threshold: 0.8 },
        fraud: {},
        valuation: {},
        partial_loss: {},
        token_budgets: {},
        crew_verbose: true,
      },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useSystemHealth).mockReturnValue({
      data: {
        status: 'healthy',
        database: 'sqlite',
        total_claims: 42,
      },
      isLoading: false,
      error: null,
    } as never);
  });

  it('renders system config and health', () => {
    render(
      <Wrapper>
        <SystemConfig />
      </Wrapper>
    );
    expect(screen.getByText('System Configuration')).toBeInTheDocument();
    expect(screen.getByText('System Healthy')).toBeInTheDocument();
    expect(screen.getByText(/42 claims stored/)).toBeInTheDocument();
    expect(screen.getByText('Escalation (Human-in-the-Loop)')).toBeInTheDocument();
    expect(screen.getByText('confidence_threshold')).toBeInTheDocument();
    expect(screen.getByText('true')).toBeInTheDocument();
  });

  it('shows degraded status when not healthy', () => {
    vi.mocked(useSystemHealth).mockReturnValue({
      data: {
        status: 'degraded',
        database: 'sqlite',
        total_claims: 0,
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <SystemConfig />
      </Wrapper>
    );
    expect(screen.getByText('System Degraded')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    vi.mocked(useSystemConfig).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);
    vi.mocked(useSystemHealth).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <SystemConfig />
      </Wrapper>
    );
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows error state', () => {
    vi.mocked(useSystemConfig).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Config error'),
    } as never);

    render(
      <Wrapper>
        <SystemConfig />
      </Wrapper>
    );
    expect(screen.getByText('Config error')).toBeInTheDocument();
  });
});
