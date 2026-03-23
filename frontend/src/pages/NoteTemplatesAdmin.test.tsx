import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import NoteTemplatesAdmin from './NoteTemplatesAdmin';

vi.mock('../api/queries', () => ({
  useNoteTemplates: vi.fn(),
  useCreateNoteTemplate: vi.fn(),
  useUpdateNoteTemplate: vi.fn(),
  useDeleteNoteTemplate: vi.fn(),
}));

const {
  useNoteTemplates,
  useCreateNoteTemplate,
  useUpdateNoteTemplate,
  useDeleteNoteTemplate,
} = await import('../api/queries');

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

const mockTemplates = [
  {
    id: 1,
    label: 'Initial Contact',
    body: 'Contacted claimant.',
    category: 'general',
    is_active: 1,
    sort_order: 0,
    created_by: 'admin',
    created_at: '2025-01-01T00:00:00',
    updated_at: '2025-01-01T00:00:00',
  },
  {
    id: 2,
    label: 'Coverage Verified',
    body: 'Coverage OK.',
    category: null,
    is_active: 0,
    sort_order: 1,
    created_by: null,
    created_at: '2025-01-02T00:00:00',
    updated_at: '2025-01-02T00:00:00',
  },
];

describe('NoteTemplatesAdmin', () => {
  const mutateFn = vi.fn();

  beforeEach(() => {
    vi.mocked(useNoteTemplates).mockReturnValue({
      data: mockTemplates,
      isLoading: false,
      error: null,
    } as never);
    vi.mocked(useCreateNoteTemplate).mockReturnValue({
      mutate: mutateFn,
      isPending: false,
    } as never);
    vi.mocked(useUpdateNoteTemplate).mockReturnValue({
      mutate: mutateFn,
      isPending: false,
    } as never);
    vi.mocked(useDeleteNoteTemplate).mockReturnValue({
      mutate: mutateFn,
      isPending: false,
    } as never);
  });

  it('renders page header and templates table', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <NoteTemplatesAdmin />
      </Wrapper>,
    );
    expect(screen.getByText('Note Templates')).toBeInTheDocument();
    expect(screen.getByText('Initial Contact')).toBeInTheDocument();
    expect(screen.getByText('Coverage Verified')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    vi.mocked(useNoteTemplates).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <NoteTemplatesAdmin />
      </Wrapper>,
    );
    expect(screen.getByText('Note Templates')).toBeInTheDocument();
  });

  it('shows error state', () => {
    vi.mocked(useNoteTemplates).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Network error'),
    } as never);
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <NoteTemplatesAdmin />
      </Wrapper>,
    );
    expect(screen.getByText('Network error')).toBeInTheDocument();
  });

  it('shows empty state', () => {
    vi.mocked(useNoteTemplates).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as never);
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <NoteTemplatesAdmin />
      </Wrapper>,
    );
    expect(screen.getByText(/No templates configured/)).toBeInTheDocument();
  });

  it('create form has required fields', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <NoteTemplatesAdmin />
      </Wrapper>,
    );
    expect(screen.getByLabelText('Label *')).toBeInTheDocument();
    expect(screen.getByLabelText('Body *')).toBeInTheDocument();
    expect(screen.getByLabelText('Category')).toBeInTheDocument();
    expect(screen.getByLabelText('Order')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add Template' })).toBeInTheDocument();
  });

  it('enters edit mode on edit button click', async () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <NoteTemplatesAdmin />
      </Wrapper>,
    );
    const editButtons = screen.getAllByText('Edit');
    fireEvent.click(editButtons[0]);
    await waitFor(() => {
      expect(screen.getByText('Save')).toBeInTheDocument();
      expect(screen.getByText('Cancel')).toBeInTheDocument();
    });
  });

  it('shows active/inactive toggle', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <NoteTemplatesAdmin />
      </Wrapper>,
    );
    const statusButtons = screen.getAllByRole('button').filter(
      (b) => b.textContent === 'Active' || b.textContent === 'Inactive',
    );
    expect(statusButtons.length).toBe(2);
    expect(statusButtons[0].textContent).toBe('Active');
    expect(statusButtons[1].textContent).toBe('Inactive');
  });
});
