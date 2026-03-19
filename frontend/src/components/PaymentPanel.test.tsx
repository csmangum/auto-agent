import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import PaymentPanel from './PaymentPanel';

vi.mock('../api/queries', () => ({
  useClaimPayments: vi.fn(),
  useCreatePayment: vi.fn(),
  useIssuePayment: vi.fn(),
  useClearPayment: vi.fn(),
  useVoidPayment: vi.fn(),
}));

const {
  useClaimPayments,
  useCreatePayment,
  useIssuePayment,
  useClearPayment,
  useVoidPayment,
} = await import('../api/queries');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

const mockPayments = [
  {
    id: 1,
    claim_id: 'CLM-001',
    amount: 2500,
    payee: 'John Doe',
    payee_type: 'claimant' as const,
    payment_method: 'check' as const,
    check_number: '12345',
    status: 'authorized' as const,
    authorized_by: 'adjuster-jane',
    created_at: '2025-01-15T10:00:00Z',
    updated_at: '2025-01-15T10:00:00Z',
  },
  {
    id: 2,
    claim_id: 'CLM-001',
    amount: 1500,
    payee: 'Auto Body Shop',
    payee_type: 'repair_shop' as const,
    payment_method: 'ach' as const,
    status: 'cleared' as const,
    authorized_by: 'adjuster-jane',
    cleared_at: '2025-01-18T10:00:00Z',
    created_at: '2025-01-16T10:00:00Z',
    updated_at: '2025-01-18T10:00:00Z',
  },
];

describe('PaymentPanel', () => {
  beforeEach(() => {
    vi.mocked(useClaimPayments).mockReturnValue({
      data: { payments: mockPayments, total: 2, limit: 100, offset: 0 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useClaimPayments>);

    vi.mocked(useCreatePayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof useCreatePayment>);

    vi.mocked(useIssuePayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useIssuePayment>);

    vi.mocked(useClearPayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useClearPayment>);

    vi.mocked(useVoidPayment).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useVoidPayment>);
  });

  it('renders payment summary cards', () => {
    render(<PaymentPanel claimId="CLM-001" />, { wrapper: createWrapper() });
    expect(screen.getByText('Authorized')).toBeInTheDocument();
    expect(screen.getByText('Issued')).toBeInTheDocument();
    expect(screen.getByText('Cleared')).toBeInTheDocument();
    expect(screen.getByText('Voided')).toBeInTheDocument();
  });

  it('renders payment list', () => {
    render(<PaymentPanel claimId="CLM-001" />, { wrapper: createWrapper() });
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('Auto Body Shop')).toBeInTheDocument();
    // Amounts appear in both summary and list
    expect(screen.getAllByText('$2,500').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('$1,500').length).toBeGreaterThanOrEqual(1);
  });

  it('shows Issue button for authorized payments', () => {
    render(<PaymentPanel claimId="CLM-001" />, { wrapper: createWrapper() });
    expect(screen.getByText('Issue')).toBeInTheDocument();
  });

  it('shows Void button for authorized payments', () => {
    render(<PaymentPanel claimId="CLM-001" />, { wrapper: createWrapper() });
    expect(screen.getByText('Void')).toBeInTheDocument();
  });

  it('shows new payment form when clicking + New Payment', () => {
    render(<PaymentPanel claimId="CLM-001" />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText('+ New Payment'));
    expect(screen.getByText('Amount ($) *')).toBeInTheDocument();
    expect(screen.getByText('Payee *')).toBeInTheDocument();
    expect(screen.getByText('Payment Method *')).toBeInTheDocument();
  });

  it('renders empty state when no payments', () => {
    vi.mocked(useClaimPayments).mockReturnValue({
      data: { payments: [], total: 0, limit: 100, offset: 0 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useClaimPayments>);

    render(<PaymentPanel claimId="CLM-001" />, { wrapper: createWrapper() });
    expect(screen.getByText('No payments')).toBeInTheDocument();
  });

  it('renders loading state', () => {
    vi.mocked(useClaimPayments).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useClaimPayments>);

    render(<PaymentPanel claimId="CLM-001" />, { wrapper: createWrapper() });
    expect(screen.getByText('Payments')).toBeInTheDocument();
  });
});
