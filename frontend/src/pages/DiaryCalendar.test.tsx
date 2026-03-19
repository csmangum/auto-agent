import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DiaryCalendar from './DiaryCalendar';

vi.mock('../api/queries', () => ({
  useAllTasks: vi.fn(),
  useTaskStats: vi.fn(),
  useComplianceTemplates: vi.fn(),
}));

const { useAllTasks, useTaskStats, useComplianceTemplates } = await import('../api/queries');

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

const mockTasks = [
  { id: 1, claim_id: 'CLM-001', title: 'Contact witness', task_type: 'contact_witness', status: 'pending', priority: 'high', assigned_to: 'adj-jane', due_date: '2025-03-15', created_at: '2025-03-01T10:00:00Z' },
  { id: 2, claim_id: 'CLM-002', title: 'Review documents', task_type: 'review_documents', status: 'in_progress', priority: 'medium', assigned_to: null, due_date: '2025-03-20', created_at: '2025-03-02T10:00:00Z' },
  { id: 3, claim_id: 'CLM-003', title: 'Completed task', task_type: 'other', status: 'completed', priority: 'low', assigned_to: 'adj-bob', due_date: '2025-03-10', created_at: '2025-03-01T10:00:00Z' },
];

describe('DiaryCalendar', () => {
  beforeEach(() => {
    vi.mocked(useAllTasks).mockReturnValue({
      data: { tasks: mockTasks, total: 3, limit: 50, offset: 0 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useAllTasks>);

    vi.mocked(useTaskStats).mockReturnValue({
      data: {
        total: 10,
        by_status: { pending: 3, in_progress: 2, completed: 4, cancelled: 1 },
        by_type: {},
        by_priority: {},
        overdue: 2,
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useTaskStats>);

    vi.mocked(useComplianceTemplates).mockReturnValue({
      data: {
        templates: [
          { deadline_type: 'acknowledge', title: 'Acknowledge Claim', task_type: 'other', description: 'Acknowledge receipt', days: 15, state: 'California' },
        ],
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useComplianceTemplates>);
  });

  it('renders diary header', () => {
    render(<DiaryCalendar />, { wrapper: createWrapper() });
    expect(screen.getByText('Diary / Calendar')).toBeInTheDocument();
  });

  it('shows task stats', () => {
    render(<DiaryCalendar />, { wrapper: createWrapper() });
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('In Progress')).toBeInTheDocument();
    expect(screen.getByText('Overdue')).toBeInTheDocument();
  });

  it('renders tasks in list view by default', () => {
    render(<DiaryCalendar />, { wrapper: createWrapper() });
    expect(screen.getByText('Contact witness')).toBeInTheDocument();
    expect(screen.getByText('Review documents')).toBeInTheDocument();
    expect(screen.getByText('Completed task')).toBeInTheDocument();
  });

  it('shows compliance templates', () => {
    render(<DiaryCalendar />, { wrapper: createWrapper() });
    expect(screen.getByText('Acknowledge Claim')).toBeInTheDocument();
  });

  it('toggles to calendar view', () => {
    render(<DiaryCalendar />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText('Calendar'));
    // Calendar should show day headers
    expect(screen.getByText('Sun')).toBeInTheDocument();
    expect(screen.getByText('Mon')).toBeInTheDocument();
  });

  it('toggles back to list view', () => {
    render(<DiaryCalendar />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText('Calendar'));
    fireEvent.click(screen.getByText('List'));
    expect(screen.getByText('Contact witness')).toBeInTheDocument();
  });

  it('shows filter controls', () => {
    render(<DiaryCalendar />, { wrapper: createWrapper() });
    expect(screen.getByText('All Statuses')).toBeInTheDocument();
    expect(screen.getByText('All Types')).toBeInTheDocument();
  });

  it('renders empty state when no tasks', () => {
    vi.mocked(useAllTasks).mockReturnValue({
      data: { tasks: [], total: 0, limit: 50, offset: 0 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useAllTasks>);

    render(<DiaryCalendar />, { wrapper: createWrapper() });
    expect(screen.getByText('No tasks found')).toBeInTheDocument();
  });
});
