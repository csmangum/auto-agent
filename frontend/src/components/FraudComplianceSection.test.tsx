import { render, screen, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import FraudComplianceSection from './FraudComplianceSection';

vi.mock('../api/queries', () => ({
  useFraudReportingCompliance: vi.fn(),
}));

const { useFraudReportingCompliance } = await import('../api/queries');

const mockCompliantClaim = {
  claim_id: 'CLM-001',
  status: 'fraud_confirmed',
  claim_type: 'fraud',
  siu_case_id: 'SIU-001',
  loss_state: 'California',
  state_report_filed: true,
  nicb_filed: true,
  niss_filed: true,
  required_filing_types: ['state_bureau', 'nicb', 'niss'],
  missing_required_filings: [],
  compliant: true,
  nicb_required: true,
  nicb_due_at: '2025-02-15T00:00:00Z',
  nicb_deadline_days: 30,
  nicb_overdue: false,
  nicb_alert: null,
  filings: [
    { filing_type: 'state_bureau', report_id: 'RPT-001', state: 'California', filed_at: '2025-01-20T10:00:00Z' },
    { filing_type: 'nicb', report_id: 'RPT-002', state: 'California', filed_at: '2025-01-21T10:00:00Z' },
    { filing_type: 'niss', report_id: 'RPT-003', state: 'California', filed_at: '2025-01-22T10:00:00Z' },
  ],
};

/** Matches API: NICB overdue only when nicb_required and filing missing past due_at. */
const mockOverdueClaim = {
  claim_id: 'CLM-002',
  status: 'fraud_confirmed',
  claim_type: 'fraud',
  siu_case_id: 'SIU-002',
  loss_state: 'Texas',
  state_report_filed: true,
  nicb_filed: false,
  niss_filed: false,
  required_filing_types: ['state_bureau', 'nicb', 'niss'],
  missing_required_filings: ['nicb', 'niss'],
  compliant: false,
  nicb_required: true,
  nicb_deadline_days: 30,
  nicb_due_at: '2024-12-01T00:00:00Z',
  nicb_overdue: true,
  nicb_alert: 'overdue' as const,
  filings: [
    {
      filing_type: 'state_bureau',
      report_id: 'FRB-002',
      state: 'Texas',
      filed_at: '2024-12-02T10:00:00Z',
    },
  ],
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>{children}</BrowserRouter>
      </QueryClientProvider>
    );
  };
}

describe('FraudComplianceSection', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: null,
    } as never);
  });

  it('shows loading skeletons while data is loading', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    const { container } = render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    expect(screen.getByText(/Fraud Compliance/)).toBeInTheDocument();
    expect(container.querySelector('.skeleton-shimmer')).toBeInTheDocument();
  });

  it('shows error message when API call fails', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Network error'),
    } as never);

    render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    expect(screen.getByText('Failed to load fraud compliance data.')).toBeInTheDocument();
  });

  it('shows empty state when no fraud claims exist', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: { claims: [], total: 0 },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    expect(screen.getByText('No fraud-flagged claims found.')).toBeInTheDocument();
  });

  it('renders summary counts correctly', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: { claims: [mockCompliantClaim, mockOverdueClaim], total: 2 },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    expect(screen.getByText('Total Flagged')).toBeInTheDocument();
    expect(screen.getByText('Filings Complete')).toBeInTheDocument();
    expect(screen.getByText('Pending Filings')).toBeInTheDocument();
    expect(screen.getByText('NICB Overdue')).toBeInTheDocument();
  });

  it('renders claim rows with links', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: { claims: [mockCompliantClaim, mockOverdueClaim], total: 2 },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    const link = screen.getByRole('link', { name: 'CLM-001' });
    expect(link).toHaveAttribute('href', '/claims/CLM-001');
    expect(screen.getByRole('link', { name: 'CLM-002' })).toHaveAttribute('href', '/claims/CLM-002');
  });

  it('shows pending NICB line when required, not filed, and no alert yet', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: {
        claims: [
          {
            claim_id: 'CLM-PEND',
            status: 'fraud_confirmed',
            claim_type: 'fraud',
            siu_case_id: 'SIU-PEND',
            loss_state: 'Florida',
            state_report_filed: true,
            nicb_filed: false,
            niss_filed: true,
            required_filing_types: ['state_bureau', 'nicb', 'niss'],
            missing_required_filings: ['nicb'],
            compliant: false,
            nicb_required: true,
            nicb_deadline_days: 30,
            nicb_due_at: '2030-06-15T12:00:00Z',
            nicb_overdue: false,
            nicb_alert: null,
            filings: [],
          },
        ],
        total: 1,
      },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    const row = screen.getByRole('row', { name: /CLM-PEND/ });
    expect(within(row).getByText(/Pending/)).toBeInTheDocument();
    expect(within(row).getByText(/due/)).toBeInTheDocument();
  });

  it('shows overdue alert for overdue claims', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: { claims: [mockOverdueClaim], total: 1 },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    expect(screen.getByText('⚠ Overdue')).toBeInTheDocument();
  });

  it('shows filing badges for required filing types', () => {
    vi.mocked(useFraudReportingCompliance).mockReturnValue({
      data: { claims: [mockCompliantClaim], total: 1 },
      isLoading: false,
      error: null,
    } as never);

    render(
      <Wrapper>
        <FraudComplianceSection />
      </Wrapper>
    );
    // Filed badges show a checkmark followed by the filing type label
    const badges = document.querySelectorAll('span.inline-flex');
    const badgeTexts = Array.from(badges).map((b) => b.textContent ?? '');
    expect(badgeTexts.some((t) => t.includes('State'))).toBe(true);
    expect(badgeTexts.some((t) => t.includes('NICB'))).toBe(true);
    expect(badgeTexts.some((t) => t.includes('NISS'))).toBe(true);
  });
});
