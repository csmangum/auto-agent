import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import TaskPanel from './TaskPanel';

const mockCreateClaimTask = vi.fn();
const mockUpdateTask = vi.fn();

vi.mock('../api/client', () => ({
  createClaimTask: (...args: unknown[]) => mockCreateClaimTask(...args),
  updateTask: (...args: unknown[]) => mockUpdateTask(...args),
}));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function createWrapper() {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

const mockTasks = [
  {
    id: 1,
    title: 'Request police report',
    task_type: 'obtain_police_report',
    status: 'pending',
    priority: 'high',
    description: 'Get report from local PD',
    assigned_to: 'adjuster-jane',
    created_by: 'system',
    due_date: '2025-02-01',
    created_at: '2025-01-15T10:00:00Z',
    resolution_notes: null,
  },
  {
    id: 2,
    title: 'Completed task',
    task_type: 'review_documents',
    status: 'completed',
    priority: 'medium',
    description: null,
    assigned_to: null,
    created_by: 'adjuster-jane',
    due_date: null,
    created_at: '2025-01-14T09:00:00Z',
    resolution_notes: 'Done',
  },
];

describe('TaskPanel', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient.clear();
    mockCreateClaimTask.mockResolvedValue({ id: 99 });
    mockUpdateTask.mockResolvedValue({});
  });

  it('shows empty state when no tasks', () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={[]} />
      </Wrapper>
    );
    expect(screen.getByText('No tasks')).toBeInTheDocument();
    expect(
      screen.getByText('Create a task to track follow-up work for this claim.')
    ).toBeInTheDocument();
  });

  it('renders filter buttons and task list', () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={mockTasks} />
      </Wrapper>
    );
    expect(screen.getByText('All (2)')).toBeInTheDocument();
    expect(screen.getByText('Active (1)')).toBeInTheDocument();
    expect(screen.getByText('Done (1)')).toBeInTheDocument();
    expect(screen.getByText('Request police report')).toBeInTheDocument();
    expect(screen.getByText('Completed task')).toBeInTheDocument();
  });

  it('filters tasks by active and completed', () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={mockTasks} />
      </Wrapper>
    );
    fireEvent.click(screen.getByText('Active (1)'));
    expect(screen.getByText('Request police report')).toBeInTheDocument();
    expect(screen.queryByText('Completed task')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Done (1)'));
    expect(screen.getByText('Completed task')).toBeInTheDocument();
    expect(screen.queryByText('Request police report')).not.toBeInTheDocument();
  });

  it('toggles new task form', () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={[]} />
      </Wrapper>
    );
    expect(screen.queryByLabelText('Create new task')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '+ New Task' }));
    expect(screen.getByLabelText('Create new task')).toBeInTheDocument();
    const form = screen.getByLabelText('Create new task');
    fireEvent.click(within(form).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByLabelText('Create new task')).not.toBeInTheDocument();
  });

  it('submits create task form', async () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={[]} />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: '+ New Task' }));
    fireEvent.change(screen.getByPlaceholderText(/Request police report/i), {
      target: { value: 'New task title' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Task' }));

    await waitFor(() => {
      expect(mockCreateClaimTask).toHaveBeenCalledWith(
        'CLM-001',
        expect.objectContaining({
          title: 'New task title',
          task_type: 'gather_information',
          priority: 'medium',
        })
      );
    });
  });

  it('expands and collapses TaskCard', () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={mockTasks} />
      </Wrapper>
    );
    const taskButton = screen.getByRole('button', {
      name: /expand request police report/i,
    });
    fireEvent.click(taskButton);
    expect(screen.getByText('Get report from local PD')).toBeInTheDocument();
    expect(screen.getByText('Assigned to:')).toBeInTheDocument();
    expect(screen.getByText('adjuster-jane')).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: /collapse request police report/i })
    );
    expect(screen.queryByText('Get report from local PD')).not.toBeInTheDocument();
  });

  it('shows Start button for pending task and calls updateTask', async () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={mockTasks} />
      </Wrapper>
    );
    fireEvent.click(
      screen.getByRole('button', { name: /expand request police report/i })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(1, { status: 'in_progress' });
    });
  });

  it('Complete button calls updateTask with completed status', async () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={mockTasks} />
      </Wrapper>
    );
    fireEvent.click(
      screen.getByRole('button', { name: /expand request police report/i })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Complete' }));

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ status: 'completed' })
      );
    });
  });

  it('Block button calls updateTask with blocked status', async () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={mockTasks} />
      </Wrapper>
    );
    fireEvent.click(
      screen.getByRole('button', { name: /expand request police report/i })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Block' }));

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(1, { status: 'blocked' });
    });
  });

  it('Cancel button calls updateTask with cancelled status', async () => {
    render(
      <Wrapper>
        <TaskPanel claimId="CLM-001" tasks={mockTasks} />
      </Wrapper>
    );
    fireEvent.click(
      screen.getByRole('button', { name: /expand request police report/i })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(1, { status: 'cancelled' });
    });
  });
});
