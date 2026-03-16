import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ClaimDetail from './ClaimDetail';

vi.mock('../api/queries', () => ({
  useClaim: vi.fn(),
  useClaimHistory: vi.fn(),
  useClaimReserveHistory: vi.fn(),
  useClaimReserveAdequacy: vi.fn(),
  useClaimWorkflows: vi.fn(),
  usePatchClaimReserve: vi.fn(),
}));

const {
  useClaim,
  useClaimHistory,
  useClaimReserveHistory,
  useClaimReserveAdequacy,
  useClaimWorkflows,
  usePatchClaimReserve,
} = await import('../api/queries');

const mockClaim = {
  id: 'CLM-001',
  policy_number: 'POL-001',
  vin: '1HGBH41JXMN109186',
  vehicle_year: 2020,
  vehicle_make: 'Honda',
  vehicle_model: 'Accord',
  incident_date: '2025-01-15',
  incident_description: 'Rear-end collision',
  damage_description: 'Bumper damage',
  estimated_damage: 5000,
  payout_amount: 4500,
  claim_type: 'new',
  status: 'open',
  created_at: '2025-01-15 10:00:00',
  updated_at: '2025-01-16 14:00:00',
};

function createWrapper(initialPath = '/claims/CLM-001') {
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

describe('ClaimDetail', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useClaim).mockReturnValue({
      data: mockClaim,
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useClaimHistory).mockReturnValue({
      data: { claim_id: 'CLM-001', history: [], total: 0, limit: null, offset: 0 },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useClaimReserveHistory).mockReturnValue({
      data: { claim_id: 'CLM-001', history: [], limit: 50 },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useClaimReserveAdequacy).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useClaimWorkflows).mockReturnValue({
      data: { claim_id: 'CLM-001', workflows: [] },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(usePatchClaimReserve).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as never);
  });

  it('renders claim overview', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    expect(screen.getByText('CLM-001')).toBeInTheDocument();
    expect(screen.getByText('POL-001')).toBeInTheDocument();
    expect(screen.getByText('1HGBH41JXMN109186')).toBeInTheDocument();
    expect(screen.getByText('Rear-end collision')).toBeInTheDocument();
    expect(screen.getByText('Bumper damage')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    expect(document.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows error state', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Claim not found'),
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    expect(screen.getByText('Claim not found')).toBeInTheDocument();
  });

  it('switches to audit tab', () => {
    vi.mocked(useClaimHistory).mockReturnValue({
      data: {
        claim_id: 'CLM-001',
        history: [{ action: 'created', created_at: '2025-01-15 10:00:00' }],
        total: 1,
        limit: null,
        offset: 0,
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /audit log/i }));
    expect(screen.getByText('Audit History')).toBeInTheDocument();
  });

  it('switches to workflows tab and shows empty state', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /workflows/i }));
    expect(screen.getByText('No workflow runs')).toBeInTheDocument();
  });

  it('switches to documents tab and shows empty state when no attachments', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /documents/i }));
    expect(screen.getByText('Documents & Attachments')).toBeInTheDocument();
    expect(screen.getByText('No documents')).toBeInTheDocument();
  });

  it('shows attachments in documents tab when present', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: {
        ...mockClaim,
        attachments: [
          { url: '/api/claims/CLM-001/attachments/invoice.pdf', type: 'pdf', description: 'Medical invoice' },
          { url: '/api/claims/CLM-001/attachments/photo.jpg', type: 'photo', description: 'Damage photo' },
        ],
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /documents/i }));
    expect(screen.getByText('Medical invoice')).toBeInTheDocument();
    expect(screen.getByText('Damage photo')).toBeInTheDocument();
    const viewLinks = screen.getAllByText('View →');
    expect(viewLinks).toHaveLength(2);
  });

  it('switches to reserve tab and shows adjust reserve form', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /reserve/i }));
    expect(screen.getByText('Adjust Reserve')).toBeInTheDocument();
    expect(screen.getByLabelText(/amount/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update Reserve' })).toBeInTheDocument();
  });

  it('shows workflow runs when present', () => {
    vi.mocked(useClaimWorkflows).mockReturnValue({
      data: {
        claim_id: 'CLM-001',
        workflows: [
          {
            id: 1,
            claim_id: 'CLM-001',
            claim_type: 'new',
            router_output: 'routed',
            workflow_output: 'done',
            created_at: '2025-01-15 10:00:00',
          },
        ],
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /workflows/i }));
    expect(screen.getByText('Run #1')).toBeInTheDocument();
    expect(screen.getByText('routed')).toBeInTheDocument();
    expect(screen.getByText('done')).toBeInTheDocument();
  });
});
