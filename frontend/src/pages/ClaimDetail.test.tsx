import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ClaimDetail from './ClaimDetail';

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

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
  useCreatePartyRelationship: vi.fn(),
  useDeletePartyRelationship: vi.fn(),
  useActiveNoteTemplates: vi.fn(),
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
  useCreatePartyRelationship,
  useDeletePartyRelationship,
  useActiveNoteTemplates,
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
      mutateAsync: vi.fn().mockResolvedValue(undefined),
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
    vi.mocked(useCreatePartyRelationship).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as never);
    vi.mocked(useDeletePartyRelationship).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as never);
    vi.mocked(useActiveNoteTemplates).mockReturnValue({
      data: [
        { id: 1, label: 'Initial Contact', body: 'Contacted claimant.', category: null, is_active: 1, sort_order: 0, created_by: null, created_at: '', updated_at: '' },
      ],
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

  it('keeps reserve inputs when update fails', () => {
    const mutate = vi.fn(
      (_vars: unknown, opts?: { onError?: (e: Error) => void }) => {
        opts?.onError?.(new Error('Server error'));
      }
    );
    vi.mocked(usePatchClaimReserve).mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: /reserve/i }));

    const amountInput = screen.getByLabelText(/amount/i);
    const reasonInput = screen.getByLabelText(/reason/i);
    fireEvent.change(amountInput, { target: { value: '9999' } });
    fireEvent.change(reasonInput, { target: { value: 'Keep me' } });
    fireEvent.click(screen.getByRole('button', { name: 'Update Reserve' }));

    expect(mutate).toHaveBeenCalled();
    expect(amountInput).toHaveValue(9999);
    expect(reasonInput).toHaveValue('Keep me');
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
    expect(screen.getByText('$12,000 sought')).toBeInTheDocument();
    expect(screen.getByText('vs Other Insurance Co')).toBeInTheDocument();
    expect(screen.getByText('vs ACME Ins')).toBeInTheDocument();
    expect(screen.getByText('pending')).toBeInTheDocument();
    expect(screen.getByText('Arbitration: AAA')).toBeInTheDocument();
    expect(screen.getByText(/Liability: 25%/)).toBeInTheDocument();
    expect(screen.getByText(/BI demand basis/)).toBeInTheDocument();
    expect(screen.getByText(/Recovered:.*3,000/)).toBeInTheDocument();
  });

  it('shows UCSPA compliance deadlines and denial reason', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: {
        ...mockClaim,
        acknowledgment_due: '2025-02-01',
        investigation_due: '2025-03-01',
        payment_due: '2025-04-01',
        acknowledged_at: '2025-01-20T10:00:00',
        settlement_agreed_at: '2025-01-25T12:00:00',
        denial_letter_sent_at: '2025-01-28T09:00:00',
        denial_reason: 'Coverage excluded',
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <ClaimDetail />
      </Wrapper>
    );

    expect(screen.getByText('UCSPA & deadlines')).toBeInTheDocument();
    expect(screen.getByText('Acknowledgment due')).toBeInTheDocument();
    expect(screen.getByText('Investigation due')).toBeInTheDocument();
    expect(screen.getByText('Payment due')).toBeInTheDocument();
    expect(screen.getByText('Denial reason')).toBeInTheDocument();
    expect(screen.getByText('Coverage excluded')).toBeInTheDocument();
  });

  it('shows parties section with relationships', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: {
        ...mockClaim,
        parties: [
          {
            id: 1,
            party_type: 'claimant',
            name: 'Jane Doe',
            email: 'jane@example.com',
            phone: '555-1234',
            relationships: [],
          },
          {
            id: 2,
            party_type: 'attorney',
            name: 'Law Firm',
            role: 'representation',
            relationships: [
              {
                id: 10,
                from_party_id: 2,
                to_party_id: 1,
                relationship_type: 'represented_by',
              },
            ],
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

    expect(screen.getByText('Parties')).toBeInTheDocument();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getByText('Law Firm')).toBeInTheDocument();
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
    expect(screen.getByText('555-1234')).toBeInTheDocument();
    const relTexts = screen.getAllByText(/represented by/);
    expect(relTexts.length).toBeGreaterThanOrEqual(1);
  });

  it('shows documents in documents tab', () => {
    vi.mocked(useClaimDocuments).mockReturnValue({
      data: {
        claim_id: 'CLM-001',
        documents: [
          {
            id: 1,
            claim_id: 'CLM-001',
            document_type: 'estimate',
            review_status: 'pending',
            storage_key: 'docs/estimate_v1.pdf',
            version: 1,
            created_at: '2025-01-15',
            received_from: 'claimant',
            privileged: false,
            url: '/files/estimate.pdf',
          },
        ],
        total: 1,
        limit: 100,
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

    fireEvent.click(screen.getByRole('button', { name: /documents/i }));
    const docHeadings = screen.getAllByText('Documents (1)');
    expect(docHeadings.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('estimate_v1.pdf')).toBeInTheDocument();
    expect(screen.getByText(/from claimant/)).toBeInTheDocument();
  });

  it('shows notes and follow-up messages in notes tab', () => {
    vi.mocked(useClaim).mockReturnValue({
      data: {
        ...mockClaim,
        notes: [
          {
            id: 1,
            note: 'Contacted claimant',
            actor_id: 'adjuster',
            created_at: '2025-01-16T10:00:00',
          },
        ],
        follow_up_messages: [
          {
            id: 1,
            claim_id: 'CLM-001',
            user_type: 'claimant',
            message_content: 'Please update me',
            status: 'sent',
            created_at: '2025-01-17T10:00:00',
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

    const notesTab = screen.getAllByRole('button').find(b => b.textContent?.includes('Notes ('));
    expect(notesTab).toBeTruthy();
    fireEvent.click(notesTab!);
    expect(screen.getByText('Contacted claimant')).toBeInTheDocument();
    expect(screen.getByText('Please update me')).toBeInTheDocument();
  });

  it('shows document requests in documents tab', () => {
    vi.mocked(useDocumentRequests).mockReturnValue({
      data: {
        claim_id: 'CLM-001',
        requests: [
          {
            id: 1,
            claim_id: 'CLM-001',
            document_type: 'police_report',
            requested_from: 'police dept',
            status: 'requested',
            created_at: '2025-01-16',
          },
        ],
        total: 1,
        limit: 100,
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

    fireEvent.click(screen.getByRole('button', { name: /documents/i }));
    expect(screen.getByText('Document Requests (1)')).toBeInTheDocument();
    expect(screen.getByText(/From: police dept/)).toBeInTheDocument();
  });
});
