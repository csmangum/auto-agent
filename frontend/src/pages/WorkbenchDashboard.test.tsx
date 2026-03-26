import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import WorkbenchDashboard from './WorkbenchDashboard';

vi.mock('../api/queries', () => ({
  useReviewQueue: vi.fn(),
  useOverdueTasks: vi.fn(),
  useTaskStats: vi.fn(),
}));

const { useReviewQueue, useOverdueTasks, useTaskStats } = await import('../api/queries');

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

describe('WorkbenchDashboard', () => {
  beforeEach(() => {
    vi.mocked(useReviewQueue).mockReturnValue({
      data: {
        claims: [
          { id: 'CLM-001', priority: 'critical', status: 'needs_review', policy_number: 'P1', vin: 'V1' },
          { id: 'CLM-002', priority: 'high', status: 'needs_review', policy_number: 'P2', vin: 'V2' },
          { id: 'CLM-003', priority: 'medium', status: 'needs_review', policy_number: 'P3', vin: 'V3' },
        ],
        total: 3,
        limit: 200,
        offset: 0,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    } as ReturnType<typeof useReviewQueue>);

    vi.mocked(useOverdueTasks).mockReturnValue({
      data: {
        tasks: [
          { id: 1, claim_id: 'CLM-001', title: 'Follow up claimant', task_type: 'follow_up_claimant', status: 'pending', priority: 'high', due_date: '2025-01-01' },
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    } as ReturnType<typeof useOverdueTasks>);

    vi.mocked(useTaskStats).mockReturnValue({
      data: {
        total: 20,
        by_status: { pending: 5, in_progress: 3, completed: 10, cancelled: 2 },
        by_type: {},
        by_priority: {},
        overdue: 1,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    } as ReturnType<typeof useTaskStats>);
  });

  it('renders the workbench header', () => {
    render(<WorkbenchDashboard />, { wrapper: createWrapper() });
    expect(screen.getByText('My Workbench')).toBeInTheDocument();
  });

  it('shows stat cards with data', () => {
    render(<WorkbenchDashboard />, { wrapper: createWrapper() });
    expect(screen.getByText('Review Queue')).toBeInTheDocument();
    expect(screen.getByText('Active Tasks')).toBeInTheDocument();
    expect(screen.getByText('Overdue')).toBeInTheDocument();
  });

  it('shows priority breakdown', () => {
    render(<WorkbenchDashboard />, { wrapper: createWrapper() });
    expect(screen.getByText('Queue by Priority')).toBeInTheDocument();
  });

  it('shows overdue tasks', () => {
    render(<WorkbenchDashboard />, { wrapper: createWrapper() });
    expect(screen.getByText('Overdue Tasks')).toBeInTheDocument();
    expect(screen.getByText('Follow up claimant')).toBeInTheDocument();
  });

  it('shows quick action links', () => {
    render(<WorkbenchDashboard />, { wrapper: createWrapper() });
    expect(screen.getByText('My Assignments')).toBeInTheDocument();
    expect(screen.getByText('Assignment Queue')).toBeInTheDocument();
    expect(screen.getByText('Diary / Calendar')).toBeInTheDocument();
    expect(screen.getByText('New Claim')).toBeInTheDocument();
  });

  it('renders loading state', () => {
    vi.mocked(useReviewQueue).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: 0,
    } as ReturnType<typeof useReviewQueue>);
    vi.mocked(useOverdueTasks).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: 0,
    } as ReturnType<typeof useOverdueTasks>);
    vi.mocked(useTaskStats).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: 0,
    } as ReturnType<typeof useTaskStats>);

    render(<WorkbenchDashboard />, { wrapper: createWrapper() });
    expect(screen.getByText('My Workbench')).toBeInTheDocument();
    // Stat cards show '—' when loading
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });
});
