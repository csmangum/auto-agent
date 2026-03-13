import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import NewClaimForm from './NewClaimForm';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

const mockProcessClaimAsync = vi.fn();
const mockStreamClaimUpdates = vi.fn();

const MOCK_POLICIES = {
  policies: [
    {
      policy_number: 'POL-001',
      status: 'active',
      vehicles: [
        { vin: '1HGBH41JXMN109186', vehicle_year: 2021, vehicle_make: 'Honda', vehicle_model: 'Accord' },
        { vin: '5YJSA1E26HF123456', vehicle_year: 2022, vehicle_make: 'Tesla', vehicle_model: 'Model 3' },
      ],
    },
    {
      policy_number: 'POL-002',
      status: 'active',
      vehicles: [{ vin: '2HGFG3B54CH501234', vehicle_year: 2020, vehicle_make: 'Honda', vehicle_model: 'Civic' }],
    },
  ],
};

const mockGenerateIncidentDetails = vi.fn();

vi.mock('../api/client', () => ({
  processClaimAsync: (...args: unknown[]) => mockProcessClaimAsync(...args),
  streamClaimUpdates: (...args: unknown[]) => mockStreamClaimUpdates(...args),
  generateIncidentDetails: (...args: unknown[]) => mockGenerateIncidentDetails(...args),
  getPolicies: () => Promise.resolve(MOCK_POLICIES),
}));

function fillRequiredFields() {
  fireEvent.click(screen.getByLabelText(/policy number/i));
  fireEvent.click(screen.getByText('POL-001'));
  fireEvent.change(screen.getByLabelText(/vehicle year/i), { target: { value: '2021' } });
  fireEvent.change(screen.getByLabelText(/vehicle make/i), { target: { value: 'Honda' } });
  fireEvent.change(screen.getByLabelText(/vehicle model/i), { target: { value: 'Accord' } });
  fireEvent.change(screen.getByLabelText(/vin/i), { target: { value: '1HGBH41JXMN109186' } });
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
    renderWithProviders(<NewClaimForm />);
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

    renderWithProviders(<NewClaimForm />);

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

    renderWithProviders(<NewClaimForm />);

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

    renderWithProviders(<NewClaimForm />);

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

    renderWithProviders(<NewClaimForm />);

    fillRequiredFields();
    fireEvent.click(screen.getByRole('button', { name: 'Submit Claim' }));

    await waitFor(() => {
      expect(screen.getByText(/CLM-1/)).toBeInTheDocument();
    });

    const resetButtons = screen.getAllByRole('button', { name: 'New Claim' });
    fireEvent.click(resetButtons[resetButtons.length - 1]);

    await waitFor(() => {
      expect(screen.getByLabelText(/policy number/i)).toHaveTextContent('Select a policy…');
      expect(screen.queryByText(/CLM-1/)).not.toBeInTheDocument();
    });
  });

  it('cascading filter: select year first then policy completes vehicle selection', async () => {
    renderWithProviders(<NewClaimForm />);

    fireEvent.change(screen.getByLabelText(/vehicle year/i), { target: { value: '2021' } });
    fireEvent.click(screen.getByLabelText(/policy number/i));
    fireEvent.click(screen.getByText('POL-001'));
    fireEvent.change(screen.getByLabelText(/vehicle make/i), { target: { value: 'Honda' } });
    fireEvent.change(screen.getByLabelText(/vehicle model/i), { target: { value: 'Accord' } });
    fireEvent.change(screen.getByLabelText(/vin/i), { target: { value: '1HGBH41JXMN109186' } });

    await waitFor(() => {
      expect(screen.getByLabelText(/vin/i)).toHaveValue('1HGBH41JXMN109186');
    });
  });
});
