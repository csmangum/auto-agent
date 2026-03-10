import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Documentation from './Documentation';

vi.mock('../api/queries', () => ({
  useDocs: vi.fn(),
  useDoc: vi.fn(),
}));

const { useDocs, useDoc } = await import('../api/queries');

function createWrapper(initialPath = '/docs/intro') {
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

describe('Documentation', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useDocs).mockReturnValue({
      data: { pages: [{ slug: 'intro', title: 'Introduction', available: true }] },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useDoc).mockReturnValue({
      data: { slug: 'intro', title: 'Introduction', content: '# Hello' },
      isLoading: false,
      error: null,
    } as never);
  });

  it('renders documentation sidebar and content', () => {
    render(
      <Wrapper>
        <Documentation />
      </Wrapper>
    );
    expect(screen.getByText('Documentation')).toBeInTheDocument();
    expect(screen.getAllByText('Introduction').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    vi.mocked(useDocs).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);
    vi.mocked(useDoc).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <Documentation />
      </Wrapper>
    );
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows error state', () => {
    vi.mocked(useDocs).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load'),
    } as never);

    render(
      <Wrapper>
        <Documentation />
      </Wrapper>
    );
    expect(screen.getByText('Failed to load')).toBeInTheDocument();
  });
});
