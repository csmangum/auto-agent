import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ClaimsList from './ClaimsList';

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
  limit: 25,
  offset: 0,
};

vi.mock('../api/queries', () => ({
  useClaims: vi.fn(),
}));

const { useClaims } = await import('../api/queries');

function createWrapper(initialPath = '/claims') {
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

describe('ClaimsList', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useClaims).mockClear();
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);
  });

  it('renders page header and claim count', () => {
    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(screen.getByText('Claims')).toBeInTheDocument();
    expect(screen.getByText('1 claim')).toBeInTheDocument();
  });

  it('renders claim table with data', () => {
    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(screen.getByText('CLM-001')).toBeInTheDocument();
    expect(screen.getByText('POL-001')).toBeInTheDocument();
  });

  it('shows loading skeleton when loading', () => {
    vi.mocked(useClaims).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows error when API fails', () => {
    vi.mocked(useClaims).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to fetch'),
    } as never);

    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(screen.getByText('Failed to fetch')).toBeInTheDocument();
  });

  it('renders filter dropdowns', () => {
    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    const comboboxes = screen.getAllByRole('combobox');
    expect(comboboxes.length).toBeGreaterThanOrEqual(2);
  });

  it('renders search input', () => {
    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(screen.getByRole('searchbox', { name: /search claims/i })).toBeInTheDocument();
  });

  it('renders sort controls', () => {
    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(screen.getByRole('combobox', { name: /sort by/i })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /sort order/i })).toBeInTheDocument();
  });

  it('shows plural when multiple claims', () => {
    vi.mocked(useClaims).mockReturnValue({
      data: { ...mockClaimsData, total: 5, claims: [] },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(screen.getByText('5 claims')).toBeInTheDocument();
  });

  it('shows pagination when total exceeds page size', () => {
    vi.mocked(useClaims).mockReturnValue({
      data: {
        claims: Array.from({ length: 25 }, (_, i) => ({
          ...mockClaimsData.claims[0],
          id: `CLM-${String(i + 1).padStart(3, '0')}`,
        })),
        total: 50,
        limit: 25,
        offset: 0,
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );
    expect(screen.getByText(/Showing 1–25 of 50/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
  });

  it('shows clear filters when status filter is applied', () => {
    const WrapperWithParams = createWrapper('/claims?status=open');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
  });

  it('shows clear filters when archived checkbox is checked', () => {
    const WrapperWithParams = createWrapper('/claims?include_archived=true');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
  });

  it('shows clear filters when search is active', () => {
    const WrapperWithParams = createWrapper('/claims?search=CLM');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
  });

  it('calls useClaims with filter params when status filter is set', () => {
    const WrapperWithParams = createWrapper('/claims?status=open');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );

    expect(useClaims).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'open', limit: 25, offset: 0 })
    );
  });

  it('calls useClaims with search param when search URL param is set', () => {
    const WrapperWithParams = createWrapper('/claims?search=CLM-001');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );

    expect(useClaims).toHaveBeenCalledWith(
      expect.objectContaining({ search: 'CLM-001' })
    );
  });

  it('calls useClaims with sort params from URL', () => {
    const WrapperWithParams = createWrapper('/claims?sort_by=estimated_damage&sort_order=asc');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );

    expect(useClaims).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'estimated_damage', sort_order: 'asc' })
    );
  });

  it('pagination next button advances page and reflects in URL', () => {
    vi.mocked(useClaims).mockImplementation((params: { offset?: number }) => ({
      data: {
        claims: Array.from({ length: 25 }, (_, i) => ({
          ...mockClaimsData.claims[0],
          id: `CLM-${String((params.offset ?? 0) + i + 1).padStart(3, '0')}`,
        })),
        total: 50,
        limit: 25,
        offset: params.offset ?? 0,
      },
      isLoading: false,
      error: null,
    }) as never);

    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );

    expect(screen.getByText('Showing 1–25 of 50')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByText('Showing 26–50 of 50')).toBeInTheDocument();
  });

  it('page param in URL initialises to correct page', () => {
    const WrapperWithParams = createWrapper('/claims?page=2');
    vi.mocked(useClaims).mockReturnValue({
      data: {
        claims: mockClaimsData.claims,
        total: 50,
        limit: 25,
        offset: 25,
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );

    expect(useClaims).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 25 })
    );
    expect(screen.getByText('Showing 26–50 of 50')).toBeInTheDocument();
  });

  it('changing status filter updates useClaims params', () => {
    const WrapperWithParams = createWrapper('/claims');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );

    const statusSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(statusSelect, { target: { value: 'closed' } });

    expect(useClaims).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'closed', limit: 25, offset: 0 })
    );
  });

  it('clear filters resets all controls including archived and purged', async () => {
    const WrapperWithParams = createWrapper('/claims?status=open&include_archived=true&include_purged=true&search=CLM');
    vi.mocked(useClaims).mockReturnValue({
      data: mockClaimsData,
      isLoading: false,
      error: null,
    } as never);

    render(
      <WrapperWithParams>
        <ClaimsList />
      </WrapperWithParams>
    );

    // Verify checkboxes are checked before clearing
    expect(screen.getByLabelText(/include archived/i)).toBeChecked();
    expect(screen.getByLabelText(/include purged/i)).toBeChecked();

    fireEvent.click(screen.getByRole('button', { name: /clear filters/i }));

    // After clearing, checkboxes should be unchecked and search input empty
    await waitFor(() => {
      expect(screen.getByLabelText(/include archived/i)).not.toBeChecked();
      expect(screen.getByLabelText(/include purged/i)).not.toBeChecked();
      expect(screen.getByRole('searchbox', { name: /search claims/i })).toHaveValue('');
    });

    // useClaims should be called without the filter params
    expect(useClaims).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ status: 'open', include_archived: true })
    );
  });

  it('search input updates searchInput state', () => {
    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );

    const searchInput = screen.getByRole('searchbox', { name: /search claims/i });
    fireEvent.change(searchInput, { target: { value: 'CLM-001' } });
    expect(searchInput).toHaveValue('CLM-001');
  });

  it('sort order dropdown changes sort_order param', async () => {
    render(
      <Wrapper>
        <ClaimsList />
      </Wrapper>
    );

    const sortOrderSelect = screen.getByRole('combobox', { name: /sort order/i });
    fireEvent.change(sortOrderSelect, { target: { value: 'asc' } });

    await waitFor(() =>
      expect(useClaims).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort_order: 'asc' })
      )
    );
  });
});
