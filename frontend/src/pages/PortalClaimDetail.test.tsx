import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PortalProvider } from '../context/PortalContext';
import PortalClaimDetail from './PortalClaimDetail';

const mockGetClaim = vi.fn();
const mockGetClaimHistory = vi.fn();
const mockGetDocuments = vi.fn();
const mockGetRepairStatus = vi.fn();
const mockGetPayments = vi.fn();
const mockGetDocumentRequests = vi.fn();

vi.mock('../api/portalClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/portalClient')>();
  return {
    ...actual,
    portalApi: {
      ...actual.portalApi,
      getClaim: (...args: unknown[]) => mockGetClaim(...args),
      getClaimHistory: (...args: unknown[]) => mockGetClaimHistory(...args),
      getDocuments: (...args: unknown[]) => mockGetDocuments(...args),
      getRepairStatus: (...args: unknown[]) => mockGetRepairStatus(...args),
      getPayments: (...args: unknown[]) => mockGetPayments(...args),
      getDocumentRequests: (...args: unknown[]) => mockGetDocumentRequests(...args),
    },
  };
});

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

const mockClaim = {
  id: 'CLM-001',
  status: 'open',
  claim_type: 'partial_loss',
  vehicle_year: 2021,
  vehicle_make: 'Honda',
  vehicle_model: 'Accord',
  incident_description: 'Rear-end collision',
  incident_date: '2025-01-10',
  estimated_damage: 5000,
  payout_amount: null,
  created_at: '2025-01-15T10:00:00Z',
  follow_up_messages: [],
};

function createWrapper(initialPath = '/portal/claims/CLM-001') {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <PortalProvider>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
              <Route path="/portal/claims/:claimId" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </PortalProvider>
    );
  };
}

describe('PortalClaimDetail', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient.clear();
    mockGetClaim.mockResolvedValue(mockClaim);
    mockGetClaimHistory.mockResolvedValue({ history: [] });
    mockGetDocuments.mockResolvedValue({ documents: [], total: 0 });
    mockGetRepairStatus.mockResolvedValue({
      history: [],
      latest: null,
      cycle_time_days: null,
    });
    mockGetPayments.mockResolvedValue({ payments: [], total: 0 });
    mockGetDocumentRequests.mockResolvedValue({ document_requests: [], total: 0 });
  });

  it('shows loading state', () => {
    mockGetClaim.mockImplementation(() => new Promise(() => {}));
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('shows error state and Back to My Claims', async () => {
    mockGetClaim.mockRejectedValue(new Error('Claim not found'));
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim not found');
    expect(screen.getByRole('button', { name: 'Back to My Claims' })).toBeInTheDocument();
  });

  it('renders claim and tab switching', async () => {
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    expect(mockGetPayments).toHaveBeenCalledWith('CLM-001');
    expect(mockGetDocumentRequests).toHaveBeenCalledWith('CLM-001');

    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Documents')).toBeInTheDocument();
    expect(screen.getByText('Messages')).toBeInTheDocument();
    expect(screen.getByText('Repair Status')).toBeInTheDocument();
    expect(screen.getByText('Payments')).toBeInTheDocument();
    expect(screen.getByText('Rental')).toBeInTheDocument();
    expect(screen.getByText('Dispute')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Documents'));
    expect(mockGetDocuments).toHaveBeenCalledWith('CLM-001');

    fireEvent.click(screen.getByText('Repair Status'));
    expect(mockGetRepairStatus).toHaveBeenCalledWith('CLM-001');

    fireEvent.click(screen.getByText('Payments'));
    expect(mockGetPayments).toHaveBeenCalledWith('CLM-001');

    fireEvent.click(screen.getByText('Rental'));
    await screen.findByText('Loss of use and rental');
    expect(mockGetRepairStatus).toHaveBeenCalledWith('CLM-001');
  });

  it('shows status tab content', async () => {
    mockGetClaimHistory.mockResolvedValue({
      history: [
        {
          id: 1,
          action: 'status_change',
          new_status: 'open',
          created_at: '2025-01-15T10:00:00Z',
        },
      ],
    });
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    expect(screen.getByText('Claim Summary')).toBeInTheDocument();
    expect(screen.getByText('Timeline')).toBeInTheDocument();
    expect(screen.getByText(/Rear-end collision/)).toBeInTheDocument();
  });

  it('shows documents tab empty state', async () => {
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    fireEvent.click(screen.getByText('Documents'));
    await screen.findByText('No documents');
  });

  it('shows documents tab with docs', async () => {
    mockGetDocuments.mockResolvedValue({
      documents: [
        {
          id: 1,
          document_type: 'estimate',
          received_date: '2025-01-16',
          storage_key: 'claim/CLM-001/doc1.pdf',
        },
      ],
      total: 1,
    });
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    fireEvent.click(screen.getByText('Documents'));
    await screen.findByText(/estimate/);
  });

  it('shows messages tab', async () => {
    mockGetClaim.mockResolvedValue({
      ...mockClaim,
      follow_up_messages: [
        {
          id: 1,
          claim_id: 'CLM-001',
          user_type: 'claimant',
          message_content: 'When will I get my check?',
          status: 'responded',
          created_at: '2025-01-16T10:00:00Z',
        },
      ],
    });
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    fireEvent.click(screen.getByText('Messages'));
    await screen.findByText(/When will I get my check/i);
  });

  it('shows rental tab with requests, repair context, and coordination payments', async () => {
    mockGetDocumentRequests.mockResolvedValue({
      document_requests: [
        {
          id: 1,
          document_type: 'rental_receipt',
          status: 'requested',
          requested_at: '2025-01-18T10:00:00Z',
          requested_from: 'claimant',
        },
      ],
      total: 1,
    });
    mockGetRepairStatus.mockResolvedValue({
      history: [],
      latest: { status: 'paint', authorization_id: 'AUTH-99' },
      cycle_time_days: 3,
    });
    mockGetPayments.mockResolvedValue({
      payments: [
        {
          id: 1,
          amount: 120,
          payee: 'Hertz',
          payee_type: 'rental_company',
          status: 'issued',
          issued_at: '2025-01-19T10:00:00Z',
          payment_method: 'ach',
        },
        {
          id: 2,
          amount: 200,
          payee: 'Jane',
          payee_type: 'claimant',
          status: 'issued',
          external_ref: 'workflow_rental:run1',
          payment_method: 'check',
        },
      ],
      total: 2,
    });
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    fireEvent.click(screen.getByText('Rental'));
    await screen.findByText('Loss of use and rental');
    await screen.findByText(/Repair timeline/i);
    expect(screen.getByText('AUTH-99')).toBeInTheDocument();
    expect(screen.getByText(/rental receipt/i)).toBeInTheDocument();
    expect(screen.getByText(/\$120/)).toBeInTheDocument();
    expect(screen.getByText(/\$200/)).toBeInTheDocument();
  });

  it('shows payments tab with payments', async () => {
    mockGetPayments.mockResolvedValue({
      payments: [
        {
          id: 1,
          amount: 4500,
          payee: 'John Doe',
          payee_type: 'claimant',
          status: 'issued',
          issued_at: '2025-01-20T10:00:00Z',
        },
      ],
      total: 1,
    });
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    fireEvent.click(screen.getByText('Payments'));
    await screen.findByText('$4,500');
  });

  it('shows repair tab empty for non-partial-loss', async () => {
    mockGetClaim.mockResolvedValue({
      ...mockClaim,
      claim_type: 'total_loss',
    });
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    fireEvent.click(screen.getByText('Repair Status'));
    await screen.findByText('Repair status not available');
  });

  it('shows dispute tab when cannot dispute', async () => {
    mockGetClaim.mockResolvedValue({
      ...mockClaim,
      status: 'denied',
    });
    render(
      <Wrapper>
        <PortalClaimDetail />
      </Wrapper>
    );
    await screen.findByText('Claim CLM-001...');
    fireEvent.click(screen.getByText('Dispute'));
    await screen.findByText('Disputes not available');
  });
});
