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
  useAddClaimNote: vi.fn(),
  useClaimDocuments: vi.fn(),
  useUploadDocument: vi.fn(),
  useUpdateDocument: vi.fn(),
  useDocumentRequests: vi.fn(),
  useCreateDocumentRequest: vi.fn(),
  useClaimPayments: vi.fn(),
  useCreatePayment: vi.fn(),
  useIssuePayment: vi.fn(),
  useClearPayment: vi.fn(),
  useVoidPayment: vi.fn(),
  usePolicies: vi.fn(),
}));

const {
  useClaim,
  useClaimHistory,
  useClaimReserveHistory,
  useClaimReserveAdequacy,
  useClaimWorkflows,
  usePatchClaimReserve,
  useAddClaimNote,
  useClaimDocuments,
  useUploadDocument,
  useUpdateDocument,
  useDocumentRequests,
  useCreateDocumentRequest,
  useClaimPayments,
  useCreatePayment,
  useIssuePayment,
  useClearPayment,
  useVoidPayment,
  usePolicies,
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
    vi.mocked(useAddClaimNote).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as never);
    vi.mocked(useClaimDocuments).mockReturnValue({
      data: { claim_id: 'CLM-001', documents: [], total: 0, limit: 100, offset: 0 },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useUploadDocument).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as never);
    vi.mocked(useUpdateDocument).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as never);
    vi.mocked(useDocumentRequests).mockReturnValue({
      data: { claim_id: 'CLM-001', requests: [], total: 0, limit: 100, offset: 0 },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useCreateDocumentRequest).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as never);
    vi.mocked(useClaimPayments).mockReturnValue({
      data: { payments: [], total: 0, limit: 100, offset: 0 },
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useCreatePayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    } as never);
    vi.mocked(useIssuePayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as never);
    vi.mocked(useClearPayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as never);
    vi.mocked(useVoidPayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as never);
    vi.mocked(usePolicies).mockReturnValue({
      data: { policies: [] },
      isLoading: false,
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
    fireEvent.click(screen.getByRole('button', { name: /audit/i }));
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

  it('switches to documents tab and shows upload area', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /documents/i }));
    expect(screen.getByText('Upload Document')).toBeInTheDocument();
    expect(screen.getByText('No documents')).toBeInTheDocument();
  });

  it('switches to notes tab and shows add note form', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    // Tab button text: "📝 Notes (0)"
    const notesTab = screen.getAllByRole('button').find(b => b.textContent?.includes('Notes ('));
    expect(notesTab).toBeTruthy();
    fireEvent.click(notesTab!);
    expect(screen.getByText('Quick Templates')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Enter your note...')).toBeInTheDocument();
  });

  it('switches to payments tab and shows empty state', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /payments/i }));
    expect(screen.getByText('No payments')).toBeInTheDocument();
  });

  it('switches to comms log tab', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /comms log/i }));
    expect(screen.getByText('Communication Log')).toBeInTheDocument();
  });

  it('switches to coverage tab', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /coverage/i }));
    expect(screen.getByText('Policy not found')).toBeInTheDocument();
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

  it('handles reserve form input changes', () => {
    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /reserve/i }));
    
    const amountInput = screen.getByLabelText(/amount/i);
    const reasonInput = screen.getByLabelText(/reason/i);
    
    fireEvent.change(amountInput, { target: { value: '10000' } });
    expect(amountInput).toHaveValue(10000);
    
    fireEvent.change(reasonInput, { target: { value: 'Supplemental estimate' } });
    expect(reasonInput).toHaveValue('Supplemental estimate');
  });

  it('shows reserve adequacy warning when inadequate', () => {
    vi.mocked(useClaimReserveAdequacy).mockReturnValue({
      data: {
        adequate: false,
        warnings: ['Reserve is below estimated damage'],
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /reserve/i }));
    expect(screen.getByText('⚠ Needs attention')).toBeInTheDocument();
    expect(screen.getByText('Reserve is below estimated damage')).toBeInTheDocument();
  });

  it('shows reserve history when present', () => {
    vi.mocked(useClaimReserveHistory).mockReturnValue({
      data: {
        claim_id: 'CLM-001',
        history: [
          {
            id: 1,
            claim_id: 'CLM-001',
            old_amount: 5000,
            new_amount: 7500,
            reason: 'Supplemental estimate',
            actor_id: 'user@example.com',
            created_at: '2025-01-16 10:00:00',
          },
        ],
        limit: 50,
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /reserve/i }));
    expect(screen.getByText('Supplemental estimate')).toBeInTheDocument();
    expect(screen.getByText('user@example.com')).toBeInTheDocument();
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

  it('shows liability fields in claim details when present', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: {
        ...mockClaim,
        liability_percentage: 40,
        liability_basis: 'Comparative negligence per police report',
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );

    expect(screen.getByText('Liability %')).toBeInTheDocument();
    expect(screen.getByText('40%')).toBeInTheDocument();
    expect(screen.getByText('Liability Basis')).toBeInTheDocument();
    expect(screen.getByText('Comparative negligence per police report')).toBeInTheDocument();
  });

  it('shows subrogation cases with amounts, carrier, status badges, and liability line', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: {
        ...mockClaim,
        subrogation_cases: [
          {
            id: 1,
            claim_id: 'CLM-001',
            case_id: 'SUB-2025-01',
            amount_sought: 12000,
            opposing_carrier: 'Other Insurance Co',
            status: 'pending',
            liability_percentage: 25,
            liability_basis: 'BI demand basis',
            recovery_amount: 3000,
          },
          {
            id: 2,
            claim_id: 'CLM-001',
            case_id: 'SUB-ARB',
            amount_sought: 5000,
            opposing_carrier: 'ACME Ins',
            status: 'partial',
            arbitration_status: 'filed',
            arbitration_forum: 'AAA',
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

    expect(screen.getByText('Subrogation Cases')).toBeInTheDocument();
    expect(screen.getByText('SUB-2025-01')).toBeInTheDocument();
    expect(screen.getByText('SUB-ARB')).toBeInTheDocument();
    const firstCase = screen.getByText('SUB-2025-01').closest('div.rounded-lg');
    expect(firstCase).toBeTruthy();
    expect(firstCase).toHaveTextContent('$12,000');
    expect(firstCase).toHaveTextContent('sought');
    expect(screen.getByText('vs Other Insurance Co')).toBeInTheDocument();
    expect(screen.getByText('vs ACME Ins')).toBeInTheDocument();
    expect(screen.getByText('pending')).toBeInTheDocument();
    expect(screen.getByText('Arbitration: AAA')).toBeInTheDocument();
    expect(firstCase).toHaveTextContent('Liability: 25%');
    expect(firstCase).toHaveTextContent('BI demand basis');
    expect(firstCase).toHaveTextContent('Recovered:');
    expect(firstCase).toHaveTextContent('3,000');
  });
});
