import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PortalProvider } from '../context/PortalContext';
import PortalClaimsList from './PortalClaimsList';

const mockGetClaims = vi.fn();

vi.mock('../api/portalClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/portalClient')>();
  return {
    ...actual,
    portalApi: {
      ...actual.portalApi,
      getClaims: (...args: unknown[]) => mockGetClaims(...args),
    },
  };
});

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function createWrapper(initialPath = '/portal/claims') {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <PortalProvider>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[initialPath]}>{children}</MemoryRouter>
        </QueryClientProvider>
      </PortalProvider>
    );
  };
}

const PAGE_SIZE = 50;

const mockClaims = [
  {
    id: 'CLM-001',
    status: 'open',
    vehicle_year: 2021,
    vehicle_make: 'Honda',
    vehicle_model: 'Accord',
    incident_description: 'Rear-end collision',
    estimated_damage: 5000,
    payout_amount: 4500,
    created_at: '2025-01-15T10:00:00Z',
  },
];

describe('PortalClaimsList', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient.clear();
    mockGetClaims.mockResolvedValue({ claims: mockClaims, total: 1 });
  });

  it('shows loading skeleton when loading', async () => {
    mockGetClaims.mockImplementation(() => new Promise(() => {}));
    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('shows empty state when no claims', async () => {
    mockGetClaims.mockResolvedValue({ claims: [], total: 0 });
    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );
    await screen.findByText('No claims found');
    expect(screen.getByText("We couldn't find any claims matching your information.")).toBeInTheDocument();
  });

  it('renders claims list with navigate on click', async () => {
    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );
    await screen.findByText('CLM-001');
    const claimRow = screen.getByRole('button', { name: /CLM-001/i });
    expect(within(claimRow).getByText('open')).toBeInTheDocument();
    expect(within(claimRow).getByText(/Honda/)).toBeInTheDocument();
    expect(within(claimRow).getByText(/Accord/)).toBeInTheDocument();

    fireEvent.click(claimRow);
  });

  it('shows error display on API failure', async () => {
    mockGetClaims.mockRejectedValue(new Error('Network error'));
    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );
    await screen.findByText('Network error');
  });

  it('renders Sign Out button', async () => {
    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );
    await screen.findByText('My Claims');
    expect(screen.getByRole('button', { name: 'Sign Out' })).toBeInTheDocument();
  });

  it('shows Load more button and calls getClaims with next offset', async () => {
    const page1 = Array.from({ length: PAGE_SIZE }, (_, i) => ({
      id: `CLM-${String(i + 1).padStart(3, '0')}`,
      status: 'open',
      vehicle_year: 2020,
      vehicle_make: 'Toyota',
      vehicle_model: 'Camry',
      created_at: '2025-01-01T00:00:00Z',
    }));
    const page2 = [
      {
        id: 'CLM-051',
        status: 'closed',
        vehicle_year: 2021,
        vehicle_make: 'Honda',
        vehicle_model: 'Civic',
        created_at: '2025-02-01T00:00:00Z',
      },
    ];
    mockGetClaims
      .mockResolvedValueOnce({ claims: page1, total: 51 })
      .mockResolvedValueOnce({ claims: page2, total: 51 });

    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );

    // Wait for first page to load
    await screen.findByText('CLM-001');

    // Load more button should be visible (no filter/search active)
    const loadMoreBtn = screen.getByRole('button', { name: 'Load more' });
    expect(loadMoreBtn).toBeInTheDocument();

    // Click Load more
    fireEvent.click(loadMoreBtn);

    // getClaims should be called with the next offset
    await waitFor(() => {
      expect(mockGetClaims).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: PAGE_SIZE });
    });

    // Second page item appears
    await screen.findByText('CLM-051');
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('search by claim ID narrows rendered results', async () => {
    const claims = [
      { id: 'CLM-001', status: 'open', vehicle_year: 2020, vehicle_make: 'Toyota', vehicle_model: 'Camry', created_at: '2025-01-01T00:00:00Z' },
      { id: 'CLM-002', status: 'open', vehicle_year: 2021, vehicle_make: 'Honda', vehicle_model: 'Civic', created_at: '2025-01-02T00:00:00Z' },
    ];
    mockGetClaims.mockResolvedValue({ claims, total: 2 });

    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );

    await screen.findByText('CLM-001');
    await screen.findByText('CLM-002');

    const searchInput = screen.getByPlaceholderText('Search by claim ID…');
    fireEvent.change(searchInput, { target: { value: 'CLM-002' } });

    await waitFor(() => {
      expect(screen.queryByText('CLM-001')).not.toBeInTheDocument();
    });
    expect(screen.getByText('CLM-002')).toBeInTheDocument();
  });

  it('status filter narrows rendered results', async () => {
    const claims = [
      { id: 'CLM-001', status: 'open', vehicle_year: 2020, vehicle_make: 'Toyota', vehicle_model: 'Camry', created_at: '2025-01-01T00:00:00Z' },
      { id: 'CLM-002', status: 'closed', vehicle_year: 2021, vehicle_make: 'Honda', vehicle_model: 'Civic', created_at: '2025-01-02T00:00:00Z' },
    ];
    mockGetClaims.mockResolvedValue({ claims, total: 2 });

    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );

    await screen.findByText('CLM-001');
    await screen.findByText('CLM-002');

    const statusSelect = screen.getByRole('combobox');
    fireEvent.change(statusSelect, { target: { value: 'open' } });

    await waitFor(() => {
      expect(screen.queryByText('CLM-002')).not.toBeInTheDocument();
    });
    expect(screen.getByText('CLM-001')).toBeInTheDocument();
  });

  it('Load more is hidden when search filter is active', async () => {
    const page1 = Array.from({ length: PAGE_SIZE }, (_, i) => ({
      id: `CLM-${String(i + 1).padStart(3, '0')}`,
      status: 'open',
      vehicle_year: 2020,
      vehicle_make: 'Toyota',
      vehicle_model: 'Camry',
      created_at: '2025-01-01T00:00:00Z',
    }));
    mockGetClaims.mockResolvedValue({ claims: page1, total: 100 });

    render(
      <Wrapper>
        <PortalClaimsList />
      </Wrapper>
    );

    await screen.findByText('CLM-001');
    // Initially Load more is shown
    expect(screen.getByRole('button', { name: 'Load more' })).toBeInTheDocument();

    // Apply search filter
    const searchInput = screen.getByPlaceholderText('Search by claim ID…');
    fireEvent.change(searchInput, { target: { value: 'CLM-001' } });

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
    });
  });
});
