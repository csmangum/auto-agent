import { render, screen, fireEvent } from '@testing-library/react';
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
    await screen.findByText('Claim CLM-001...');
    expect(screen.getByText('open')).toBeInTheDocument();
    expect(screen.getByText(/Honda/)).toBeInTheDocument();
    expect(screen.getByText(/Accord/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('Claim CLM-001...'));
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
});
