import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Skills from './Skills';

vi.mock('../api/queries', () => ({
  useSkills: vi.fn(),
}));

const { useSkills } = await import('../api/queries');

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

describe('Skills', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useSkills).mockReturnValue({
      data: {
        groups: {
          'Core Routing': [
            { name: 'adjuster', role: 'Claims Adjuster', goal: 'Process claims' },
          ],
        },
      },
      isLoading: false,
      error: null,
    } as never);
  });

  it('renders skills grouped by workflow', () => {
    render(
      <Wrapper>
        <Skills />
      </Wrapper>
    );
    expect(screen.getByText('Agent Skills')).toBeInTheDocument();
    expect(screen.getByText('Core Routing')).toBeInTheDocument();
    expect(screen.getByText('Claims Adjuster')).toBeInTheDocument();
    expect(screen.getByText('adjuster.md')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    vi.mocked(useSkills).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Skills />
      </Wrapper>
    );
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows empty state when no skills', () => {
    vi.mocked(useSkills).mockReturnValue({
      data: { groups: {} },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Skills />
      </Wrapper>
    );
    expect(screen.getByText('No skills found')).toBeInTheDocument();
  });

  it('shows error state', () => {
    vi.mocked(useSkills).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('API error'),
    } as never);

    render(
      <Wrapper>
        <Skills />
      </Wrapper>
    );
    expect(screen.getByText('API error')).toBeInTheDocument();
  });
});
