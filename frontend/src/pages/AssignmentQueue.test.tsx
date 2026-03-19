import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AssignmentQueue from './AssignmentQueue';

vi.mock('../api/queries', () => ({
  useReviewQueue: vi.fn(),
  useAssignClaim: vi.fn(),
}));

const { useReviewQueue, useAssignClaim } = await import('../api/queries');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

const mockClaims = [
  { id: 'CLM-001', priority: 'critical', claim_type: 'fraud', status: 'needs_review', assignee: null, review_started_at: '2025-01-10T10:00:00Z', due_at: null, policy_number: 'P1', vin: 'V1' },
  { id: 'CLM-002', priority: 'low', claim_type: 'partial_loss', status: 'needs_review', assignee: 'adj-jane', review_started_at: '2025-01-12T14:00:00Z', due_at: '2025-01-20T00:00:00Z', policy_number: 'P2', vin: 'V2' },
  { id: 'CLM-003', priority: 'high', claim_type: 'total_loss', status: 'needs_review', assignee: null, review_started_at: '2025-01-11T08:00:00Z', due_at: null, policy_number: 'P3', vin: 'V3' },
];

describe('AssignmentQueue', () => {
  beforeEach(() => {
    vi.mocked(useReviewQueue).mockReturnValue({
      data: { claims: mockClaims, total: 3, limit: 25, offset: 0 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useReviewQueue>);

    vi.mocked(useAssignClaim).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useAssignClaim>);
  });

  it('renders queue header', () => {
    render(<AssignmentQueue />, { wrapper: createWrapper() });
    expect(screen.getByText('Assignment Queue')).toBeInTheDocument();
  });

  it('shows claim count badge', () => {
    render(<AssignmentQueue />, { wrapper: createWrapper() });
    expect(screen.getByText('3 claims')).toBeInTheDocument();
  });

  it('renders claims sorted by priority (critical first)', () => {
    render(<AssignmentQueue />, { wrapper: createWrapper() });
    const rows = screen.getAllByRole('row');
    // Header + 3 data rows
    expect(rows).toHaveLength(4);
    // First data row should be critical (CLM-001)
    expect(rows[1]).toHaveTextContent('CLM-001');
    // Second should be high (CLM-003)
    expect(rows[2]).toHaveTextContent('CLM-003');
    // Third should be low (CLM-002)
    expect(rows[3]).toHaveTextContent('CLM-002');
  });

  it('shows assign button for each claim', () => {
    render(<AssignmentQueue />, { wrapper: createWrapper() });
    const assignButtons = screen.getAllByText('Assign');
    expect(assignButtons.length).toBeGreaterThanOrEqual(1);
  });

  it('shows unassigned label when no assignee', () => {
    render(<AssignmentQueue />, { wrapper: createWrapper() });
    const unassigned = screen.getAllByText('Unassigned');
    expect(unassigned.length).toBeGreaterThanOrEqual(1);
  });

  it('opens assign input when clicking assign', () => {
    render(<AssignmentQueue />, { wrapper: createWrapper() });
    const assignButtons = screen.getAllByText('Assign');
    fireEvent.click(assignButtons[0]);
    expect(screen.getByPlaceholderText('Assignee ID (min 2 chars)')).toBeInTheDocument();
  });

  it('renders empty state when queue is empty', () => {
    vi.mocked(useReviewQueue).mockReturnValue({
      data: { claims: [], total: 0, limit: 25, offset: 0 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useReviewQueue>);

    render(<AssignmentQueue />, { wrapper: createWrapper() });
    expect(screen.getByText('Queue is empty')).toBeInTheDocument();
  });

  it('renders loading state', () => {
    vi.mocked(useReviewQueue).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useReviewQueue>);

    render(<AssignmentQueue />, { wrapper: createWrapper() });
    expect(screen.getByText('Assignment Queue')).toBeInTheDocument();
  });

  it('shows filter controls', () => {
    render(<AssignmentQueue />, { wrapper: createWrapper() });
    expect(screen.getByText('All Priorities')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Filter by assignee...')).toBeInTheDocument();
  });
});
