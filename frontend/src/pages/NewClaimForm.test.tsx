import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
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

  describe('Generate incident details', () => {
    function fillVehicleForGenerate() {
      fireEvent.click(screen.getByLabelText(/policy number/i));
      fireEvent.click(screen.getByText('POL-001'));
      fireEvent.change(screen.getByLabelText(/vehicle year/i), { target: { value: '2021' } });
      fireEvent.change(screen.getByLabelText(/vehicle make/i), { target: { value: 'Honda' } });
      fireEvent.change(screen.getByLabelText(/vehicle model/i), { target: { value: 'Accord' } });
    }

    it('Generate button is disabled when vehicle fields incomplete', () => {
      renderWithProviders(<NewClaimForm />);
      const generateBtn = screen.getByRole('button', { name: 'Generate' });
      expect(generateBtn).toBeDisabled();
    });

    it('Generate calls API and populates form on success', async () => {
      mockGenerateIncidentDetails.mockResolvedValue({
        incident_date: '2025-02-10',
        incident_description: 'Parking lot fender bender.',
        damage_description: 'Front left fender dent.',
        estimated_damage: 1800,
      });

      renderWithProviders(<NewClaimForm />);
      fillVehicleForGenerate();

      fireEvent.click(screen.getByRole('button', { name: 'Generate' }));

      await waitFor(() => {
        expect(mockGenerateIncidentDetails).toHaveBeenCalledWith(
          expect.objectContaining({
            vehicle_year: 2021,
            vehicle_make: 'Honda',
            vehicle_model: 'Accord',
          })
        );
      });

      await waitFor(() => {
        expect(screen.getByLabelText(/incident date/i)).toHaveValue('2025-02-10');
        expect(screen.getByLabelText(/incident description/i)).toHaveValue('Parking lot fender bender.');
        expect(screen.getByLabelText(/damage description/i)).toHaveValue('Front left fender dent.');
        const damageInput = screen.getByLabelText(/estimated damage/i);
        expect(damageInput.value).toBe('1800');
      });
    });

    it('Generate shows error message on API failure', async () => {
      mockGenerateIncidentDetails.mockRejectedValue(new Error('Mock Crew must be enabled'));

      renderWithProviders(<NewClaimForm />);
      fillVehicleForGenerate();

      fireEvent.click(screen.getByRole('button', { name: 'Generate' }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Mock Crew must be enabled');
      });
    });

    it('Generate shows "Generating…" while loading', async () => {
      let resolveGenerate: (v: unknown) => void = () => {};
      mockGenerateIncidentDetails.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveGenerate = resolve;
          })
      );

      renderWithProviders(<NewClaimForm />);
      fillVehicleForGenerate();

      fireEvent.click(screen.getByRole('button', { name: 'Generate' }));

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /generating/i })).toBeInTheDocument();
      });

      await act(async () => {
        resolveGenerate({
          incident_date: '2025-02-10',
          incident_description: 'Test.',
          damage_description: 'Test.',
          estimated_damage: null,
        });
      });
    });

    it('Generate passes scenario prompt when provided', async () => {
      mockGenerateIncidentDetails.mockResolvedValue({
        incident_date: '2025-02-10',
        incident_description: 'Flood damage.',
        damage_description: 'Water damage.',
        estimated_damage: null,
      });

      renderWithProviders(<NewClaimForm />);
      fillVehicleForGenerate();
      fireEvent.change(screen.getByLabelText(/scenario/i), {
        target: { value: 'flood damage' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Generate' }));

      await waitFor(() => {
        expect(mockGenerateIncidentDetails).toHaveBeenCalledWith(
          expect.objectContaining({ prompt: 'flood damage' })
        );
      });
    });

    it('Reset clears generate error', async () => {
      mockProcessClaimAsync.mockResolvedValue({ claim_id: 'CLM-1' });
      mockStreamClaimUpdates.mockImplementation((_id: string, onUpdate: (d: unknown) => void) => {
        queueMicrotask(() => onUpdate({ claim: { id: 'CLM-1', status: 'open' }, done: true }));
        return () => {};
      });
      mockGenerateIncidentDetails.mockRejectedValue(new Error('Generate failed'));

      renderWithProviders(<NewClaimForm />);
      fillVehicleForGenerate();
      fireEvent.change(screen.getByLabelText(/incident description/i), {
        target: { value: 'Test incident' },
      });
      fireEvent.change(screen.getByLabelText(/damage description/i), {
        target: { value: 'Test damage' },
      });
      fireEvent.change(screen.getByLabelText(/vin/i), { target: { value: '1HGBH41JXMN109186' } });
      fireEvent.click(screen.getByRole('button', { name: 'Submit Claim' }));

      await waitFor(() => {
        expect(screen.getByText(/CLM-1/)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: 'Generate' }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Generate failed');
      });

      fireEvent.click(screen.getByRole('button', { name: 'New Claim' }));

      await waitFor(() => {
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      });
    });
  });
});
