import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import NewClaimForm from './NewClaimForm';

const mockProcessClaimAsync = vi.fn();
const mockStreamClaimUpdates = vi.fn();

vi.mock('../api/client', () => ({
  processClaimAsync: (...args: unknown[]) => mockProcessClaimAsync(...args),
  streamClaimUpdates: (...args: unknown[]) => mockStreamClaimUpdates(...args),
}));

function fillRequiredFields() {
  fireEvent.change(screen.getByLabelText(/policy number/i), { target: { value: 'POL-001' } });
  fireEvent.change(screen.getByLabelText(/vin/i), { target: { value: '1HGBH41JXMN109186' } });
  fireEvent.change(screen.getByLabelText(/vehicle make/i), { target: { value: 'Honda' } });
  fireEvent.change(screen.getByLabelText(/vehicle model/i), { target: { value: 'Accord' } });
  fireEvent.change(screen.getByLabelText(/incident description/i), {
    target: { value: 'Rear-end collision' },
  });
  fireEvent.change(screen.getByLabelText(/damage description/i), {
    target: { value: 'Bumper damage' },
  });
}

describe('NewClaimForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders form with required fields', () => {
    render(
      <MemoryRouter>
        <NewClaimForm />
      </MemoryRouter>
    );
    expect(screen.getByText('New Claim')).toBeInTheDocument();
    expect(screen.getByLabelText(/policy number/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/vin/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/incident date/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /submit|process/i })).toBeInTheDocument();
  });

  it('submits form and shows streaming updates', async () => {
    mockProcessClaimAsync.mockResolvedValue({ claim_id: 'CLM-1' });
    mockStreamClaimUpdates.mockImplementation((_id: string, onUpdate: (d: unknown) => void) => {
      queueMicrotask(() => {
        onUpdate({ claim: { id: 'CLM-1', status: 'open', claim_type: 'new' }, done: false });
        onUpdate({ done: true });
      });
      return () => {};
    });

    render(
      <MemoryRouter>
        <NewClaimForm />
      </MemoryRouter>
    );

    fillRequiredFields();
    fireEvent.click(screen.getByRole('button', { name: 'Submit Claim' }));

    await waitFor(() => {
      expect(mockProcessClaimAsync).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(mockStreamClaimUpdates).toHaveBeenCalledWith('CLM-1', expect.any(Function), expect.any(Function));
    });

    await waitFor(() => {
      expect(screen.getByText(/Claim CLM-1|CLM-1/)).toBeInTheDocument();
    });
  });

  it('shows error when processClaimAsync fails', async () => {
    mockProcessClaimAsync.mockRejectedValue(new Error('Network error'));

    render(
      <MemoryRouter>
        <NewClaimForm />
      </MemoryRouter>
    );

    fillRequiredFields();
    fireEvent.click(screen.getByRole('button', { name: /submit|process/i }));

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('shows error when stream callback receives error', async () => {
    mockProcessClaimAsync.mockResolvedValue({ claim_id: 'CLM-1' });
    mockStreamClaimUpdates.mockImplementation((_id: string, onUpdate: (d: unknown) => void) => {
      onUpdate({ error: 'Processing failed' });
      return () => {};
    });

    render(
      <MemoryRouter>
        <NewClaimForm />
      </MemoryRouter>
    );

    fillRequiredFields();
    fireEvent.click(screen.getByRole('button', { name: /submit|process/i }));

    await waitFor(() => {
      expect(screen.getByText('Processing failed')).toBeInTheDocument();
    });
  });

  it('reset button clears form and result state', async () => {
    mockProcessClaimAsync.mockResolvedValue({ claim_id: 'CLM-1' });
    mockStreamClaimUpdates.mockImplementation((_id: string, onUpdate: (d: unknown) => void) => {
      queueMicrotask(() => onUpdate({ claim: { id: 'CLM-1', status: 'open' }, done: true }));
      return () => {};
    });

    render(
      <MemoryRouter>
        <NewClaimForm />
      </MemoryRouter>
    );

    fillRequiredFields();
    fireEvent.click(screen.getByRole('button', { name: 'Submit Claim' }));

    await waitFor(() => {
      expect(screen.getByText(/CLM-1/)).toBeInTheDocument();
    });

    const resetButtons = screen.getAllByRole('button', { name: 'New Claim' });
    fireEvent.click(resetButtons[resetButtons.length - 1]);

    await waitFor(() => {
      expect(screen.getByLabelText(/policy number/i)).toHaveValue('');
      expect(screen.queryByText(/CLM-1/)).not.toBeInTheDocument();
    });
  });
});
