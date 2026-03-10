import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import SkillDetail from './SkillDetail';

vi.mock('../api/queries', () => ({
  useSkill: vi.fn(),
}));

const { useSkill } = await import('../api/queries');

function createWrapper(initialPath = '/skills/adjuster') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialPath]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe('SkillDetail', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useSkill).mockReturnValue({
      data: {
        name: 'adjuster',
        role: 'Claims Adjuster',
        goal: 'Process insurance claims',
        backstory: 'Experienced adjuster',
        content: '# Skill content',
      },
      isLoading: false,
      error: null,
    } as never);
  });

  it('renders skill details', () => {
    render(
      <Wrapper>
        <SkillDetail />
      </Wrapper>
    );
    expect(screen.getByText('Claims Adjuster')).toBeInTheDocument();
    expect(screen.getByText('adjuster.md')).toBeInTheDocument();
    expect(screen.getByText('Process insurance claims')).toBeInTheDocument();
    expect(screen.getByText('Experienced adjuster')).toBeInTheDocument();
    expect(screen.getByText('Skill content')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    vi.mocked(useSkill).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <SkillDetail />
      </Wrapper>
    );
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows error state', () => {
    vi.mocked(useSkill).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Not found'),
    } as never);

    render(
      <Wrapper>
        <SkillDetail />
      </Wrapper>
    );
    expect(screen.getByText('Not found')).toBeInTheDocument();
  });
});
