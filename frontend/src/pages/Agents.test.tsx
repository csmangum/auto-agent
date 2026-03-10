import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Agents from './Agents';

vi.mock('../api/queries', () => ({
  useAgentsCatalog: vi.fn(),
}));

const { useAgentsCatalog } = await import('../api/queries');

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

describe('Agents', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useAgentsCatalog).mockReturnValue({
      data: {
        crews: [
          {
            name: 'Claims Crew',
            description: 'Processes claims',
            module: 'claims_crew',
            agents: [
              {
                name: 'Adjuster',
                skill: 'adjuster',
                tools: ['search', 'calculator'],
                description: 'Adjusts claims',
              },
            ],
          },
        ],
      },
      isLoading: false,
      error: null,
    } as never);
  });

  it('renders crews and agents', () => {
    render(
      <Wrapper>
        <Agents />
      </Wrapper>
    );
    expect(screen.getByText('Agents & Crews')).toBeInTheDocument();
    expect(screen.getByText('Claims Crew')).toBeInTheDocument();
    expect(screen.getByText('Adjuster')).toBeInTheDocument();
    expect(screen.getByText('Adjusts claims')).toBeInTheDocument();
    expect(screen.getByText('search')).toBeInTheDocument();
    expect(screen.getByText('calculator')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    vi.mocked(useAgentsCatalog).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Agents />
      </Wrapper>
    );
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows empty state when no crews', () => {
    vi.mocked(useAgentsCatalog).mockReturnValue({
      data: { crews: [] },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Agents />
      </Wrapper>
    );
    expect(screen.getByText('No crews found')).toBeInTheDocument();
  });

  it('shows error state', () => {
    vi.mocked(useAgentsCatalog).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed'),
    } as never);

    render(
      <Wrapper>
        <Agents />
      </Wrapper>
    );
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });
});
