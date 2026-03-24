import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RepairPortalProvider } from '../context/RepairPortalProvider';
import {
  setRepairPortalSession,
  clearRepairPortalSession,
} from '../api/repairPortalClient';
import RepairPortalClaimDetail from './RepairPortalClaimDetail';

const mockFetch = vi.fn();

function renderPage(claimId = 'CLM-1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <RepairPortalProvider>
        <MemoryRouter initialEntries={[`/repair-portal/claims/${claimId}`]}>
          <Routes>
            <Route
              path="/repair-portal/claims/:claimId"
              element={<RepairPortalClaimDetail />}
            />
            <Route
              path="/repair-portal/login"
              element={<div data-testid="login">Login</div>}
            />
          </Routes>
        </MemoryRouter>
      </RepairPortalProvider>
    </QueryClientProvider>
  );
}

describe('RepairPortalClaimDetail', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    vi.stubGlobal('fetch', mockFetch);
    clearRepairPortalSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('redirects to login when no session', () => {
    renderPage();
    expect(screen.getByTestId('login')).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'Server error',
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/API error 500/)).toBeInTheDocument();
    });
  });

  it('renders claim detail on successful fetch', async () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'CLM-1',
        status: 'processing',
        claim_type: 'partial_loss',
        vehicle_year: 2022,
        vehicle_make: 'Honda',
        vehicle_model: 'Accord',
        vin: 'VIN123',
        incident_date: '2025-01-01',
        damage_description: 'Front bumper',
        follow_up_messages: [],
      }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/RO-CLM-1/)).toBeInTheDocument();
      expect(screen.getAllByText(/2022 Honda Accord/).length).toBeGreaterThanOrEqual(1);
    });
  });

  it('shows tabs for vehicle, progress, supplement, messages', async () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'CLM-1',
        status: 'processing',
        claim_type: 'partial_loss',
        vehicle_year: 2022,
        vehicle_make: 'Honda',
        vehicle_model: 'Accord',
        vin: 'VIN123',
        follow_up_messages: [],
      }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Vehicle & Damage')).toBeInTheDocument();
      expect(screen.getByText('Repair Progress')).toBeInTheDocument();
      expect(screen.getByText('Supplemental')).toBeInTheDocument();
      expect(screen.getByText('Messages (0)')).toBeInTheDocument();
    });
  });

  it('displays vehicle info, VIN, and damage description on details tab', async () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'CLM-1',
        status: 'processing',
        claim_type: 'partial_loss',
        vehicle_year: 2022,
        vehicle_make: 'Honda',
        vehicle_model: 'Accord',
        vin: 'VIN123',
        incident_date: '2025-01-01',
        damage_description: 'Front bumper cracked and headlight broken',
        estimated_damage: 3200,
        follow_up_messages: [],
      }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getAllByText(/2022 Honda Accord/).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText('VIN123')).toBeInTheDocument();
    expect(screen.getByText('Front bumper cracked and headlight broken')).toBeInTheDocument();
    expect(screen.getByText('$3,200')).toBeInTheDocument();
  });

  it('shows supplemental not available for non-partial_loss claim', async () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'CLM-1',
        status: 'processing',
        claim_type: 'total_loss',
        vehicle_year: 2020,
        vehicle_make: 'Toyota',
        vehicle_model: 'Camry',
        vin: 'VIN456',
        follow_up_messages: [],
      }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Supplemental')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Supplemental'));
    await screen.findByText('Supplemental not available');
    expect(screen.getByText(/Supplementals only apply to partial loss claims/)).toBeInTheDocument();
  });

  it('shows supplemental form for partial_loss claim with processing status', async () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'CLM-1',
        status: 'processing',
        claim_type: 'partial_loss',
        vehicle_year: 2022,
        vehicle_make: 'Honda',
        vehicle_model: 'Accord',
        vin: 'VIN123',
        follow_up_messages: [],
      }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Supplemental')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Supplemental'));
    await screen.findByText('Supplemental damage report');
    expect(screen.getByPlaceholderText('Describe additional damage...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Submit supplemental' })).toBeInTheDocument();
  });

  it('navigates between Repair Progress and Supplemental tabs', async () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    mockFetch.mockImplementation(async (url: string) => {
      if (String(url).includes('/repair-status')) {
        return {
          ok: true,
          json: async () => ({
            latest: { status: 'disassembly', status_updated_at: '2025-01-15T10:00:00Z' },
            history: [{ id: 1, status: 'received', status_updated_at: '2025-01-14T10:00:00Z' }],
            cycle_time_days: 1,
          }),
        } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          id: 'CLM-1',
          status: 'processing',
          claim_type: 'partial_loss',
          vehicle_year: 2022,
          vehicle_make: 'Honda',
          vehicle_model: 'Accord',
          vin: 'VIN123',
          follow_up_messages: [],
        }),
      } as Response;
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Repair Progress')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Repair Progress'));
    await screen.findByText('Status History');

    fireEvent.click(screen.getByText('Supplemental'));
    await screen.findByText('Supplemental damage report');
  });
});
